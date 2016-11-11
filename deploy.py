import boto3
import argparse
import sys
import time
import math
import logging

global_timer_begin = time.time()
global_timer_count = 1

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

asg = boto3.client("autoscaling")
elb = boto3.client("elb")
ec2 = boto3.client("ec2")
s3 = boto3.client("s3")

# This global timers were/are being used to calculate execution time.
# The idea was to give ourselves an idea how long deployments were taking.
# Bamboo kind of does this for us anyway, so it's all somewhat obsolete now,
# but the timer is used by the CLI logging algos too. See if_verbose()
def global_execution_in_seconds():
    return time.time() - global_timer_begin

def global_execution_in_minutes():
    return (time.time() - global_timer_begin) / 60

def global_timer():
    global global_timer_begin
    global global_timer_count

    global_timer_begin = time.time()
    global_timer_count = 1

    if global_timer_count ==  5:
        logging.info("Seconds (minutes) passed since execution began: %d (%d)" % (global_execution_in_seconds(), global_execution_in_minutes()))
        global_timer_count = 1
    else:
        global_timer_count += 1

def check_error(err):
    """
    If err is None (empty string == None), then there was no error.
    otherwise there was an we should log it and exit.

    Just a utility function for making error handling easier.
    """
    if err != None:
        logging.error(err)
        sys.exit(-1)

def if_verbose(message):
    """
    Centralises the output of log information.
    """
    if args.verbose:
        logging.info(message)
        global_timer()

def scale_up_autoscaling_group(asg_name, instance_count):
    """
    Sets the 'desired' flag on asg_name to instance_count.
    This means AWS will scale the ASG UP to instance_count instances.

    Once actioned via the API, the function sits and waits for the activities
    to complete.

    A timeout is used to ensure the process doesn't run forever.
    """
    if_verbose("Scaling up ASG %s to %d instances" % (asg_name, instance_count))
    asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=instance_count)
    
    activities = []
    timer = time.time()
    while(True):
        if_verbose("Sleeping for %d seconds whilst waiting for activities to come active" % args.update_timeout)
        time.sleep(args.update_timeout)

        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired on activities listing. A manual clean up is likely."

        activities = asg.describe_scaling_activities(AutoScalingGroupName=asg_name, MaxRecords=args.instance_count_step)        
        
        if len(activities["Activities"]) == args.instance_count_step:
            break

    activity_ids = [a["ActivityId"] for a in activities["Activities"]]

    if not len(activity_ids) > 0:
        return "No activities found"        
    
    if_verbose("Activities found, checking them until complete or %ds timer expires" % args.health_check_timeout)
    timer = time.time()
    while(True):
        if_verbose("Sleeping for %d seconds whilst waiting for activities to complete" % args.update_timeout)
        time.sleep(args.update_timeout)
        
        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired on activities check. A manual clean up is likely."

        completed_activities = 0
        activity_statuses = asg.describe_scaling_activities(ActivityIds=activity_ids, AutoScalingGroupName=asg_name, MaxRecords=args.instance_count_step)
        for activity in activity_statuses["Activities"]:
            if_verbose("Progress of activity ID %s: %d" % (activity["ActivityId"], activity["Progress"]))

            if activity["Progress"] == 100:
                completed_activities += 1

        if completed_activities >= args.instance_count_step:
            break
        else:
            completed_activities = 0

    if_verbose("Scaling up of ASG %s successful" % asg_name)
    return None

def check_autoscaling_group_health(asg_name, current_capacity_count):
    """
    Once an ASG is active, this function can be used to loop over the
    instances to ensure they're all coming up and going live in a 
    healthy manager. AWS does some checks for us, such as connectivity,
    and if these fails or the OS fails, then we don't get dead instances.
    """
    if_verbose("Checking the health of ASG %s" % asg_name)
    timer = time.time()
    while(True):
        if_verbose("Sleeping for %d seconds whilst waiting for ASG health" % args.update_timeout)
        time.sleep(args.update_timeout)

        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired on asg_instances count. A manual clean up is likely."

        completed_instances = 0
        asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]

        while(len(asg_instances) != current_capacity_count):
            if_verbose("Waiting for all of %s's instances (%d) to appear healthy" % (asg_name, args.instance_count_step))
            time.sleep(args.update_timeout)
            asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]

        for instance in asg_instances:
            if_verbose("Progress of ASG instance %s: %s" % (instance["InstanceId"], instance["LifecycleState"]))

            if instance["LifecycleState"] == "InService":
                completed_instances += 1

        if completed_instances >= len(asg_instances):
            if_verbose("We have %d healthy nodes and we wanted %d - moving on." % (completed_instances, len(asg_instances)))
            break
        else:
            completed_instances = 0

    if_verbose("ASG %s is healthy" % asg_name)
    return None

def check_elb_instance_health(elb_name, instances):
    """
    Checks over the ELB to ensure the instances are in a healthy state.
    Health is determined by a healthcheck on the ELB which looks at
    Peter Kia's API endpoint.
    """
    if_verbose("Checking ELB %s instance health for %s" % (elb_name, instances))
    timer = time.time()
    while (True):
        if_verbose("Sleeping for %d ELB instance health" % args.update_timeout)
        time.sleep(args.update_timeout)

        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired. A manual clean up is likely."

        healthy_elb_instances = 0
        elb_instances = elb.describe_instance_health(LoadBalancerName=elb_name, Instances=instances)
        for instance in elb_instances["InstanceStates"]:
            if_verbose("Progress of ELB instance %s: %s" % (instance["InstanceId"], instance["State"]))

            if instance["State"] == "InService":
                healthy_elb_instances += 1

        if healthy_elb_instances == len(instances):
            break
        else:
            healthy_elb_instances = 0

    if_verbose("ELB %s is healthy with instances %s" % (elb_name, elb_instances))
    return None

def current_asg_instance_count(asg_name):
    return len(asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"])

def scale_up_application(asg_name):
    """
    Wraps all the above stuff to scale the application up
    and ensure eveything comes good.
    """
    if_verbose("Scaling up %s in steps of %d" % (asg_name, args.instance_count_step))
    current_capacity_count = args.instance_count_step
    while(True):
        check_error(scale_up_autoscaling_group(asg_name, current_capacity_count))
        check_error(check_autoscaling_group_health(asg_name, current_capacity_count))

        if args.elb_name:
            asg_instances = [{"InstanceId": a["InstanceId"]} for a in asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]]
            check_error(check_elb_instance_health(args.elb_name, asg_instances))

            if args.instance_count == current_capacity_count:
                break
            else:
                current_capacity_count += args.instance_count_step
        else:
            break

    if_verbose("Scaling up %s successful" % asg_name)

def scale_down_application(asg_name):
    """
    Because we don't really care about older, now obsolete
    instances, we simply call the API and set the desired 
    instance count to 0. AWS ASG takes care of draining
    connections for us (for 300 seconds, then it kills
    anything that didn't drain.)
    """
    if_verbose("Scaling down %s." % asg_name)
    asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=0)

def lock_environment(bucket, environment):
    """
    Lock the environment via an S3 lock file.

    This used to prevent race conditions when multiple people
    or automated tasks want to do things to the environment.
    """
    s3.put_object(Bucket=bucket, Key="%s.lock"%environment)

def unlock_environment(bucket, environment):
    s3.delete_object(Bucket=bucket, Key="%s.lock"%environment)

def check_for_lock(bucket, environment):
    response = s3.list_objects(Bucket=bucket, Prefix="%s.lock"%environment)
    if 'Contents' in response:
        for file in response['Contents']:
            if file['Key'] == "%s.lock"%environment:
                return True

    return False

def handle_single_asg():
    """
    Some environments don't have an A/B setup.
    These can be managed using this method and the --single-asg
    flag.
    """
    environment_asg = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[args.environment], MaxRecords=1)
    if args.zero:
        if environment_asg["AutoScalingGroups"][0]["DesiredCapacity"] >= 1:
            if args.lock_bucket_name:
                lock_environment(args.lock_bucket_name, args.environment)

            scale_down_application(args.environment)

            if args.lock_bucket_name:
                unlock_environment(args.lock_bucket_name, args.environment)

            return 0
        else:
            check_error("ASG %s is empty. Can't zero it." % args.environment)

    if environment_asg["AutoScalingGroups"][0]["DesiredCapacity"] == 0:
        if args.lock_bucket_name:
            lock_environment(args.lock_bucket_name, args.environment)

        scale_up_application(args.environment)

        if args.lock_bucket_name:
            unlock_environment(args.lock_bucket_name, args.environment)

        return 0
    else:
        check_error("ASG %s isn't empty." % args.environment)

def main():
    """
    Check what the user asked us to do.

    Once we're A/Bing, we check to make sure the ASGs are in a 
    state we can work with, such as not both populated, or the
    environment isn't locked.
    """
    if args.lock_bucket_name:
        if check_for_lock(args.lock_bucket_name, args.environment):
            check_error("Environment is locked. Unable to proceed.")

    if args.singleasg:
        return handle_single_asg()

    if args.instance_count_step > args.instance_count:
        args.instance_count_step = args.instance_count

    if (args.instance_count_step % args.instance_count) != 0:
        check_error("Step counter %d must be divisable by %d" % (args.instance_count_step, args.instance_count))

    environment_a = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment], MaxRecords=1)
    environment_b = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment], MaxRecords=1)

    if_verbose("I have AutoScaling Groups: %s and %s" % ("%s-a" % args.environment, "%s-b" % args.environment))

    if (environment_a["AutoScalingGroups"][0]["DesiredCapacity"] == 0) and (environment_b["AutoScalingGroups"][0]["DesiredCapacity"] == 0):
        if args.lock_bucket_name:
            lock_environment(args.lock_bucket_name, args.environment)

        if args.zero:
            if args.lock_bucket_name:
                unlock_environment(args.environment)

            check_error("Nothinargs.lock_bucket_name, g to zero. Both ASGs are empty.")

        logging.info("No active ASG; starting with %s-a" % args.environment)

        if not args.dryrun:
            scale_up_application("%s-%s" % (args.environment, "a"))
            scale_down_application("%s-%s" % (args.environment, "b"))

        if args.lock_bucket_name:
            unlock_environment(args.lock_bucket_name, args.environment)

    elif len(environment_a["AutoScalingGroups"][0]["Instances"]) > 0 and len(environment_b["AutoScalingGroups"][0]["Instances"]) > 0:
        check_error("Failure. Unable to find an ASG that is empty. Both contain instances.")

    elif environment_a["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        if args.lock_bucket_name:
            lock_environment(args.lock_bucket_name, args.environment)

        if not args.zero:
            logging.info("Currently active ASG is %s-a; bringing up %s-b" % (args.environment, args.environment))

            if not args.dryrun:
                scale_up_application("%s-%s" % (args.environment, "b"))
                scale_down_application("%s-%s" % (args.environment, "a"))
        else:
            scale_down_application("%s-%s" % (args.environment, "a"))

        if args.lock_bucket_name:
            unlock_environment(args.lock_bucket_name, args.environment)

    elif environment_b["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        if args.lock_bucket_name:
            lock_environment(args.lock_bucket_name, args.environment)

        if not args.zero:
            logging.info("Currently active ASG is %s-b; bringing up %s-a" % (args.environment, args.environment))

            if not args.dryrun:
                scale_up_application("%s-%s" % (args.environment, "a"))
                scale_down_application("%s-%s" % (args.environment, "b"))
        else:
            scale_down_application("%s-%s" % (args.environment, "b"))
            
        if args.lock_bucket_name:
            unlock_environment(args.lock_bucket_name, args.environment)

    if_verbose("Finished.")
    if_verbose("Execution time: %d" % global_execution_in_minutes())

if __name__ == "__main__":
    global parser
    global args 

    parser = argparse.ArgumentParser(description='A/B Deploy Application Services')
    parser.add_argument("--lock-bucket-name", dest="lock_bucket_name", help="This is the S3 bucket to find the .lock file in (default: None)", required=False, default=None)
    parser.add_argument("--single-asg", dest="singleasg", help="Deploy to a single ASG - no A/B process - only if it's empty.", action='store_true', required=False)
    parser.add_argument("--dry-run", dest="dryrun", help="Only detect what we would do; don't run anything", action='store_true', required=False)
    parser.add_argument("--zero", dest="zero", help="Zero the currently active ASG", action='store_true', required=False, default=False)
    parser.add_argument("--environment", dest="environment", help="The environment to A/B deploy against", required=False)
    parser.add_argument("--elb-name", dest="elb_name", help="The ELB to which your ASG is linked", required=False)
    parser.add_argument("--instance-count-match", dest="instance_count_match", help="Match the new ASG instance count against the existing ASG", required=False, action='store_true')
    parser.add_argument("--instance-count", dest="instance_count", help="How many instances you want tho ASG to grow by (default: 8)", required=False, type=int, default=8)
    parser.add_argument("--instance-count-step", dest="instance_count_step", help="How many instances to scale by at a time (default: 8)", required=False, type=int, default=8)
    parser.add_argument("--update-timeout", dest="update_timeout", help="How long to wait between API calls/console updates (default: 30s)", required=False, type=int, default=5)
    parser.add_argument("--health-check-timeout", dest="health_check_timeout", help="How long to wait for the health of an ELB to stabilse (default: 600s/10m)", required=False, type=int, default=600)
    parser.add_argument("--clean-up", dest="clean_up", help="Clean up existing ASGs if they ahve instances. Very dangerous option! (default: false)", action='store_true', required=False)
    parser.add_argument("--verbose", dest="verbose", help="Print messages about progress and what step we're at (default: false)", action='store_true', required=False)
    args = parser.parse_args()
# "qtac-monitoring-pages"
    sys.exit(main())
