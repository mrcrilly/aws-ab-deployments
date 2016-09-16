import boto3
import argparse
import sys
import time
import math
import logging

asg = boto3.client("autoscaling")
elb = boto3.client("elb")
ec2 = boto3.client("ec2")

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

def scale_application(up, down):
    asg_name = "%s-%s" % (args.environment, up)
    asg_instances = []
    asg_health = False

    asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]
    current_capacity_count = args.instance_count_step

    if len(asg_instances) >= 1:
        print "Failure. There are instances inside the target ASG: %s" % up 
        sys.exit(-999)

    while(len(asg_instances) < args.instance_count):
        asg.set_desired_capacity(AutoScalingGroupName=asg_name, DesiredCapacity=len(asg_instances)+current_capacity_count)["ResponseMetadata"]["RequestId"]
        activities = asg.describe_scaling_activities(AutoScalingGroupName=asg_name, MaxRecords=current_capacity_count)
        activity_ids = [a["ActivityId"] for a in activities["Activities"]]

        if not len(activity_ids) > 0:
            print "No activities found"
            sys.exit(-999)
        
        timer = time.time()
        activities_are_incomplete = True
        while(activities_are_incomplete):
            time.sleep(args.update_timeout)
            
            if int(time.time() - timer) >= args.health_check_timeout:
                print "Health check timer expired. A manual clean up is likely."
                sys.exit(-999)

            activity_statuses = asg.describe_scaling_activities(ActivityIds=activity_ids, AutoScalingGroupName=asg_name, MaxRecords=current_capacity_count)

            for activity in activity_statuses["Activities"]:
                if activity["Progress"] == 100:
                    activities_are_incomplete = False

        asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name], MaxRecords=1)["AutoScalingGroups"][0]["Instances"]

        if not len(asg_instances) > 0:
            # Something has gone terribly wrong?
            print "No instances despite just creating one?"
            sys.exit(-999)

        elb_is_unhealthy = True
        timer = time.time()
        while (elb_is_unhealthy):
            # print "Have instance IDs, checking their health in the ELB (%s)..." % args.elb_name
            time.sleep(args.update_timeout)

            elb_instances = elb.describe_instance_health(LoadBalancerName=args.elb_name, Instances=asg_instances)
            for instance in elb_instances["InstanceStates"]:
                if instance["State"] == "InService":
                    elb_is_unhealthy = False
                else:
                    elb_is_unhealthy = True

            if int(time.time() - timer) >= args.health_check_timeout:
                print "Health check timer expired. A manual clean up is likely."
                sys.exit(-999)

        current_capacity_count += args.instance_count_step

    # while (not asg_health):
    #     print "Have %s-%s ramping up, checking instance health..." % (args.environment, up)
        
    #     for instance in asg_instances:
    #         if instance["LifecycleState"] == "InService":
    #             asg_health = True
    #         else:
    #             asg_health = False

    # active_instances = [{"InstanceId": x["InstanceId"]} for x in asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])["AutoScalingGroups"][0]["Instances"]]
    # if len(active_instances) <= 0:
    #     print "Failed to get instance IDs for %s" % (asg_name)
    #     sys.exit(-1)

    # nuture_instances_to_health(args, asg_name, active_instances)

def main():
    environment_a = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment], MaxRecords=1)
    environment_b = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment], MaxRecords=1)

    if (environment_a["AutoScalingGroups"][0]["DesiredCapacity"] == 0) and (environment_b["AutoScalingGroups"][0]["DesiredCapacity"] == 0):
        print "No active ASG; starting with 'a'"
        if not args.dryrun:
            scale_application("a", "b")

    elif len(environment_a["AutoScalingGroups"][0]["Instances"]) > 0 and len(environment_b["AutoScalingGroups"][0]["Instances"]) > 0:
        print "Failure. Unable to find an ASG that is empty. Both contain instances."
        sys.exit(-999)

    elif environment_a["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        print "Currently active ASG is %s-a" % args.environment
        if not args.dryrun:
            scale_application("b", "a")

    elif environment_b["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
        print "Currently active ASG is %s-b" % args.environment
        if not args.dryrun:
            scale_application("a", "b")


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
    args = parser.parse_args()

    sys.exit(main())
