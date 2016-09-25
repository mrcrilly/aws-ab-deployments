import boto3
import argparse
import sys
import time
import math
import logging

# logging = logging.getLogger()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

asg = boto3.client("autoscaling")
elb = boto3.client("elb")
ec2 = boto3.client("ec2")

def check_error(err):
    if err != None:
        logging.error(err)
        sys.exit(-1)

def if_verbose(message):
    if args.verbose:
        logging.info(message)

def scale_up_autoscaling_group(asg_name, instance_count):
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

def check_autoscaling_group_health(asg_name):
    if_verbose("Checking the health of ASG %s" % asg_name)
    # asg_is_not_healthy = True
    timer = time.time()
    while(True):
        if_verbose("Sleeping for %d seconds whilst waiting for ASG health" % args.update_timeout)
        time.sleep(args.update_timeout)

        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired on asg_instances count. A manual clean up is likely."

        completed_instances = 0
        asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]

        while(len(asg_instances) == 0):
            if_verbose("Waiting for %s instances (%d) to appear" % (asg_name, args.instance_count_step))
            time.sleep(args.update_timeout)
            asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]

        for instance in asg_instances:
            if_verbose("Progress of ASG instance %s: %s" % (instance["InstanceId"], instance["LifecycleState"]))

            if instance["LifecycleState"] == "InService":
                completed_instances += 1

        if completed_instances >= len(asg_instances):
            if_verbose("We have %d active nodes and we wanted %d - moving on." % (completed_instances, len(asg_instances)))
            break
        else:
            completed_instances = 0

    if_verbose("ASG %s is healthy" % asg_name)
    return None

def check_elb_instance_health(elb_name, instances):
    if_verbose("Checking ELB %s instance health for %s" % (elb_name, instances))
    # elb_is_unhealthy = True
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

        if healthy_elb_instances == len(elb_instances):
            break
        else:
            healthy_elb_instances = 0

    if_verbose("ELB %s is healthy with instances %s" % (elb_name, instances))
    return None

# def ensure_clean_cluster(elb_name):
#     if_verbose("Ensuring %s is a clean/healthy cluster" % elb_name)
#     current_instances = elb.describe_load_balancers(LoadBalancerNames=[elb_name])["LoadBalancerDescriptions"][0]["Instances"]
#     if len(current_instances) == 0:
#         if_verbose("No instances found in %s. Skipping." % asg_name)
#         return None

#     if_verbose("Instances found, checking their ELB status")
#     current_state = elb.describe_instance_health(LoadBalancerName=elb_name, Instances=current_instances)["InstanceStates"]
#     if len(current_state) == 0:
#         return "Unable to fetch ELB state"

#     for instance in current_state:
#         if instance["State"] != "InService":
#             return "ELB status is unclean. Manual clean up required."

#     if_verbose("ELB status is clean")
#     return None

def scale_up_application(asg_name):
    if_verbose("Scaling up %s in steps of %d" % (asg_name, args.instance_count_step))
    current_capacity_count = args.instance_count_step
    while(True):
        check_error(scale_up_autoscaling_group(asg_name, current_capacity_count))
        check_error(check_autoscaling_group_health(asg_name))

        asg_instances = [{"InstanceId": a["InstanceId"]} for a in asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]]
        check_error(check_elb_instance_health(args.elb_name, asg_instances))

        if args.instance_count == current_capacity_count:
            break
        else:
            current_capacity_count += args.instance_count_step

    if_verbose("Scaling up %s successful" % asg_name)

def scale_down_application(asg_name):
    if_verbose("Scaling down %s." % asg_name)
    asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=0)

def main():
    environment_a = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment], MaxRecords=1)
    environment_b = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment], MaxRecords=1)

    if_verbose("I have AutoScaling Groups: %s and %s" % ("%s-a" % args.environment, "%s-b" % args.environment))

    if (environment_a["AutoScalingGroups"][0]["DesiredCapacity"] == 0) and (environment_b["AutoScalingGroups"][0]["DesiredCapacity"] == 0):
        logging.info("No active ASG; starting with %s-a" % args.environment)

        if not args.dryrun:
            scale_up_application("%s-%s" % (args.environment, "a"))
            scale_down_application("%s-%s" % (args.environment, "b"))

    elif len(environment_a["AutoScalingGroups"][0]["Instances"]) > 0 and len(environment_b["AutoScalingGroups"][0]["Instances"]) > 0:
        check_error("Failure. Unable to find an ASG that is empty. Both contain instances.")

    elif environment_a["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        logging.info("Currently active ASG is %s-a; bringing up %s-b" % (args.environment, args.environment))

        if not args.dryrun:
            # check_error(ensure_clean_cluster(args.elb_name))
            scale_up_application("%s-%s" % (args.environment, "b"))
            scale_down_application("%s-%s" % (args.environment, "a"))

    elif environment_b["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        logging.info("Currently active ASG is %s-b; bringing up %s-a" % (args.environment, args.environment))

        if not args.dryrun:
            # check_error(ensure_clean_cluster(args.elb_name))
            scale_up_application("%s-%s" % (args.environment, "a"))
            scale_down_application("%s-%s" % (args.environment, "b"))

if __name__ == "__main__":
    global parser
    global args 

    parser = argparse.ArgumentParser(description='Build Data to S3')
    parser.add_argument("--dry-run", dest="dryrun", help="Only detect what we would do; don't run anything", action='store_true', required=False)
    parser.add_argument("--environment", dest="environment", help="The environment to A/B deploy against", required=True)
    parser.add_argument("--elb-name", dest="elb_name", help="The ELB to which your ASG is linked", required=True)
    parser.add_argument("--instance-count", dest="instance_count", help="How many instances you want tho ASG to grow by (default: 8)", required=False, type=int, default=8)
    parser.add_argument("--instance-count-step", dest="instance_count_step", help="How many instances to scale by at a time (default: 4)", required=False, type=int, default=4)
    parser.add_argument("--update-timeout", dest="update_timeout", help="How long to wait between API calls/console updates (default: 30s)", required=False, type=int, default=5)
    parser.add_argument("--health-check-timeout", dest="health_check_timeout", help="How long to wait for the health of an ELB to stabilse (default: 600s/10m)", required=False, type=int, default=600)
    parser.add_argument("--clean-up", dest="clean_up", help="Clean up existing ASGs if they ahve instances. Very dangerous option! (default: false)", action='store_true', required=False)
    parser.add_argument("--verbose", dest="verbose", help="Print messages about progress and what step we're at (default: false)", action='store_true', required=False)
    args = parser.parse_args()

    sys.exit(main())
