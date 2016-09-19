import boto3
import argparse
import sys
import time
import math
import logging

logger = logging.getLogger(__name__)
logger.setLvl(logging.ERROR)

asg = boto3.client("autoscaling")
elb = boto3.client("elb")
ec2 = boto3.client("ec2")

def check_error(err):
    if err != None:
        logging.error(err)
        sys.exit(-1)

def if_verbose(message):
    if args.verbose:
        logger.info(message)

def scale_up_autoscaling_group(asg_name, instance_count):
    if_verbose("Scaling up ASG %s by %d instances" % (asg_name, instance_count))
    asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=instance_count)
    activities = asg.describe_scaling_activities(AutoScalingGroupName=asg_name, MaxRecords=args.instance_count_step)
    activity_ids = [a["ActivityId"] for a in activities["Activities"]]

    if not len(activity_ids) > 0:
        return "No activities found"        
    
    if_verbose("Activities found, checking them until complete or %d tmer expires" % args.health_check_timeout)
    activities_are_incomplete = True
    timer = time.time()
    while(activities_are_incomplete):
        time.sleep(args.update_timeout)
        
        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired on activities check. A manual clean up is likely."

        activity_statuses = asg.describe_scaling_activities(ActivityIds=activity_ids, AutoScalingGroupName=asg_name, MaxRecords=args.instance_count_step)
        for activity in activity_statuses["Activities"]:
            if activity["Progress"] == 100:
                activities_are_incomplete = False
            else:
                activities_are_incomplete = True

    if_verbose("Scaling up of ASG %s successful" % asg_name)
    return None

def check_autoscaling_group_health(asg_name):
    if_verbose("Checking the health of ASG %s" % asg_name)
    asg_is_not_healthy = True
    timer = time.time()
    while(asg_is_not_healthy):
        time.sleep(args.update_timeout)

        asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]
        for instance in asg_instances:
            if instance["LifecycleState"] == "InService":
                asg_is_not_healthy = False
            else:
                asg_is_not_healthy = True

        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired on asg_instances count. A manual clean up is likely."

    if_verbose("ASG %s is healthy" % asg_name)
    return None

def check_elb_instance_health(elb_name, instances):
    if_verbose("Checking ELB %s instance health for %s" % (elb_name, instances))
    elb_is_unhealthy = True
    timer = time.time()
    while (elb_is_unhealthy):
        time.sleep(args.update_timeout)

        elb_instances = elb.describe_instance_health(LoadBalancerName=elb_name, Instances=instances)
        for instance in elb_instances["InstanceStates"]:
            if instance["State"] == "InService":
                elb_is_unhealthy = False
            else:
                elb_is_unhealthy = True

        if int(time.time() - timer) >= args.health_check_timeout:
            return "Health check timer expired. A manual clean up is likely."

    if_verbose("ELB %s is healthy with instances %s" (elb_name, instances))
    return None

def scale_up_application(up, down):
    asg_name = "%s-%s" % (args.environment, up)
    asg_instances = []
    asg_health = False

    if_verbose("Scaling up %s by steps of %d" % (asg_name, args.instance_count_step))
    asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]
    current_capacity_count = args.instance_count_step

    if len(asg_instances) >= 1:
        check_error("Failure. There are instances inside the target ASG: %s" % up)

    if_verbose("Entering scale_up_application loop until new ASG instances are up")
    we_have_not_deployed = True
    while(we_have_not_deployed):
        check_error(scale_up_autoscaling_group(asg_name, current_capacity_count))
        check_error(check_autoscaling_group_health(asg_name))

        asg_instances = [{"InstanceId": a["InstanceId"]} for a in asg_instances]
        check_error(check_elb_instance_health(args.elb_name, asg_instances))

        if args.instance_count == current_capacity_count:
            we_have_not_deployed = False 
        else:
            current_capacity_count += args.instance_count_step

    if_verbose("Scaling up %s successful" % asg_name)

def ensure_clean_cluster(elb_name):
    if_verbose("Ensuring %s is a clean/healthy cluster" % elb_name)
    current_instances = elb.describe_load_balancers(LoadBalancerNames=[elb_name])["LoadBalancerDescriptions"][0]["Instances"]
    if len(current_instances) == 0:
        if_verbose("No instances found in %s. Skipping." % asg_name)
        return None

    if_verbose("Instances found, checking their ELB status")
    current_state = elb.describe_instance_health(LoadBalancerName=elb_name, Instances=current_instances)["InstanceStates"]
    if len(current_state) == 0:
        return "Unable to fetch ELB state"

    for instance in current_state:
        if instance["State"] != "InService":
            return "ELB status is unclean. Manual clean up required."

    if_verbose("ELB status is clean")
    return None

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
            scale_up_application("a", "b")
            scale_down_application("%s-b"%args.environment)

    elif len(environment_a["AutoScalingGroups"][0]["Instances"]) > 0 and len(environment_b["AutoScalingGroups"][0]["Instances"]) > 0:
        check_error("Failure. Unable to find an ASG that is empty. Both contain instances.")

    elif environment_a["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        logging.info("Currently active ASG is %s-a; bringing up %s-b" % (args.environment, args.environment))

        if not args.dryrun:
            check_error(ensure_clean_cluster(args.elb_name))
            scale_up_application("b", "a")
            scale_down_application("%s-a"%args.environment)

    elif environment_b["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        logging.info("Currently active ASG is %s-b; bringing up %s-a" % (args.environment, args.environment))

        if not args.dryrun:
            check_error(ensure_clean_cluster(args.elb_name))
            scale_up_application("a", "b")
            scale_down_application("%s-b"%args.environment)

if __name__ == "__main__":
    global parser
    global args 

    parser = argparse.ArgumentParser(description='Build Data to S3')
    parser.add_argument("--dry-run", dest="dryrun", help="Only detect what we would do; don't run anything", action='store_true', required=False)
    parser.add_argument("--environment", dest="environment", help="The environment to A/B deploy against", required=True)
    parser.add_argument("--elb-name", dest="elb_name", help="The ELB to which your ASG is linked", required=True)
    parser.add_argument("--instance-count", dest="instance_count", help="How many instances you want tho ASG to grow by (default: 2)", required=False, type=int, default=2)
    parser.add_argument("--instance-count-step", dest="instance_count_step", help="How many instances to scale by at a time (default: 2)", required=False, type=int, default=2)
    parser.add_argument("--update-timeout", dest="update_timeout", help="How long to wait between API calls/console updates (default: 30s)", required=False, type=int, default=5)
    parser.add_argument("--health-check-timeout", dest="health_check_timeout", help="How long to wait for the health of an ELB to stabilse (default: 600s/10m)", required=False, type=int, default=600)
    parser.add_argument("--clean-up", dest="clean_up", help="Clean up existing ASGs if they ahve instances. Very dangerous option! (default: false)", required=False, default=False)
    parser.add_argument("--verbose", dest="verbose", help="Print messages about progress and what step we're at (default: false)", action='store_true', required=False, default=False)
    args = parser.parse_args()

    sys.exit(main())
