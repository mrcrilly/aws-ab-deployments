import boto3
import argparse
import sys
import time
import math
import logging

asg = boto3.client("autoscaling")
elb = boto3.client("elb")
ec2 = boto3.client("ec2")

def check_error(err):
    if err != None:
        print err 
        sys.exit(-999)

# def current_instance_count(group_name):
#     pass


# def check_instance_health(instance_id):
#     pass


# def check_backend_health(elb_name, instance_id):
#     pass

# def reap_and_replace_instances(args, asg_name, instances_to_reap):
#   activity_id = asg.detach_instances(InstanceIds=instances_to_reap, AutoScalingGroupName=asg_name, ShouldDecrementDesiredCapacity=True)["Activities"][0]["ActivityId"]
#   while(asg.describe_scaling_activities(ActivityIds=[activity_id], AutoScalingGroupName=asg_name, MaxRecords=1)["Activities"]["Progress"] != 100):
#       time.sleep(args.update_timeout/2)



# def nuture_instances_to_health(args, asg_name, new_instances):
#   elb_health = False
#     instances_to_reap = []
#     health_check_start = time.time()
#     while (not elb_health):
#         print "Have instance IDs, checking their health in the ELB (%s)..." % args.elb_name
#         time.sleep(args.update_timeout)

#         elb_instances = elb.describe_instance_health(LoadBalancerName=args.elb_name, Instances=new_instances)
#         for instance in elb_instances["InstanceStates"]:
#           if instance["InstanceId"] in instances_to_reap:
#               continue 

#             if instance["State"] == "InService":
#                 elb_health = True
#             else:
#                 elb_health = False

#                 if int(math.ceil(time.time() - health_check_start)) >= args.health_check_timeout:
#                   instances_to_reap.append(instance["InstanceId"])

#     if not len(instances_to_reap) == 0:
#       reap_and_replace_instances(args, asg_name, instances_to_reap)

#     asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=0)

def scale_up_autoscaling_group(asg_name, instance_count):
    asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=instance_count)
    activities = asg.describe_scaling_activities(AutoScalingGroupName=asg_name, MaxRecords=args.instance_count_step)
    activity_ids = [a["ActivityId"] for a in activities["Activities"]]

    if not len(activity_ids) > 0:
        return "No activities found"        
    
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

    return None

def check_autoscaling_group_health(asg_name):
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

    return None

def check_elb_instance_health(elb_name, instances):
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

    return None

def scale_up_application(up, down):
    asg_name = "%s-%s" % (args.environment, up)
    asg_instances = []
    asg_health = False

    asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]
    current_capacity_count = args.instance_count_step

    if len(asg_instances) >= 1:
        check_error("Failure. There are instances inside the target ASG: %s" % up)

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

def scale_down_application(asg_name):
    asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=0)

def main():
    environment_a = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment], MaxRecords=1)
    environment_b = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment], MaxRecords=1)

    if (environment_a["AutoScalingGroups"][0]["DesiredCapacity"] == 0) and (environment_b["AutoScalingGroups"][0]["DesiredCapacity"] == 0):
        print "No active ASG; starting with %s-a" % args.environment
        if not args.dryrun:
            scale_up_application("a", "b")
            scale_down_application("%s-b"%args.environment)

    elif len(environment_a["AutoScalingGroups"][0]["Instances"]) > 0 and len(environment_b["AutoScalingGroups"][0]["Instances"]) > 0:
        check_error("Failure. Unable to find an ASG that is empty. Both contain instances.")

    elif environment_a["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        print "Currently active ASG is %s-a; bringing up %s-b" % (args.environment, args.environment)
        if not args.dryrun:
            scale_up_application("b", "a")
            scale_down_application("%s-a"%args.environment)

    elif environment_b["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        print "Currently active ASG is %s-b; bringing up %s-a" % (args.environment, args.environment)
        if not args.dryrun:
            scale_up_application("a", "b")
            scale_down_application("%s-b"%args.environment)


if __name__ == "__main__":
    global parser
    global args 

    parser = argparse.ArgumentParser(description='Build Data to S3')
    parser.add_argument("--dry-run", dest="dryrun", help="Only detect what we would do; don't run anything",
                        action='store_true', required=False)
    parser.add_argument("--environment", dest="environment", help="The environment to A/B deploy against",
                        required=True)
    parser.add_argument("--elb-name", dest="elb_name", help="The ELB to which your ASG is linked", required=True)
    parser.add_argument("--instance-count", dest="instance_count",
                        help="How many instances you want tho ASG to grow by (default: 2)", required=False, type=int,
                        default=2)
    parser.add_argument("--instance-count-step", dest="instance_count_step", help="How many instances to scale by at a time (default: 2)", required=False, type=int, default=2)
    parser.add_argument("--update-timeout", dest="update_timeout",
                        help="How long to wait between API calls/console updates (default: 30s)", required=False,
                        type=int, default=5)
    parser.add_argument("--health-check-timeout", dest="health_check_timeout",
                        help="How long to wait for the health of an ELB to stabilse (default: 600s/10m)", required=False,
                        type=int, default=600)
    parser.add_argument("--clean-up", dest="clean_up", help="Clean up existing ASGs if they ahve instances. Very dangerous option! (default: false)", required=False, default=False)
    args = parser.parse_args()

    sys.exit(main())
