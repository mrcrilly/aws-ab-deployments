
import boto3
import argparse
import sys
import time

def main():
	parser = argparse.ArgumentParser(description='Build Data to S3')
	parser.add_argument("--environment", dest="environment", help="The environment to A/B deploy against", required=True)
	parser.add_argument("--elb-name", dest="elb_name", help="The ELB to which your ASG is linked", required=True)
	parser.add_argument("--instance-count", dest="instance_count", help="How many instances you want tho ASG to grow by (default: 2)", required=False, type=int, default=2)
	parser.add_argument("--update-timeout", dest="update_timeout", help="How long to wait between API calls/console updates (default: 30s)", required=False, type=int, default=10)
	args = parser.parse_args()

	asg = boto3.client("autoscaling")
	elb = boto3.client("elb")

	environment_a = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment])
	environment_b = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment])

	if environment_a["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
		print "Currently active ASG is %s-a" % args.environment

		asg.set_desired_capacity(AutoScalingGroupName="%s-b" % args.environment, DesiredCapacity=args.instance_count)
		asg_instances = []
		asg_health = False

		while(not asg_health):
			print "Have %s-b ramping up, checking instance health..." % args.environment
			time.sleep(args.update_timeout)

			asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment])["AutoScalingGroups"][0]["Instances"]
			for instance in asg_instances:
				if instance["LifecycleState"] == "InService":
					asg_health = True
				else:
					asg_health = False

		active_instances = [{"InstanceId": x["InstanceId"]} for x in asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment])["AutoScalingGroups"][0]["Instances"]]
		
		if len(active_instances) <= 0:
			print "Failed to get instance IDs for %s-b" % args.environment
			sys.exit(-1)
		
		elb_health = False

		while(not elb_health):
			print "Have instance IDs, checking their health in the ELB (%s)..." % args.elb_name
			time.sleep(args.update_timeout)

			elb_instances = elb.describe_instance_health(LoadBalancerName=args.elb_name, Instances=active_instances)
			for instance in elb_instances["InstanceStates"]:
				if instance["State"] == "InService":
					elb_health = True
				else:
					elb_health = False

		if elb_health:
			asg.set_desired_capacity(AutoScalingGroupName="%s-a" % args.environment, DesiredCapacity=0)
			print "ASG %s-a is now draining..." % args.environment
		else:
			print "ELB health is not stable, so leaving ASG %s-a untouched" % args.environment

		print "Finished."
			
	elif environment_b["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
		print "Currently active ASG is %s-b" % args.environment

		asg.set_desired_capacity(AutoScalingGroupName="%s-a" % args.environment, DesiredCapacity=args.instance_count)
		asg_instances = []
		asg_health = False

		while(not asg_health):
			print "Have %s-a ramping up, checking instance health..." % args.environment
			time.sleep(args.update_timeout)

			asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment])["AutoScalingGroups"][0]["Instances"]
			for instance in asg_instances:
				if instance["LifecycleState"] == "InService":
					asg_health = True
				else:
					asg_health = False

		active_instances = [{"InstanceId": x["InstanceId"]} for x in asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment])["AutoScalingGroups"][0]["Instances"]]
		
		if len(active_instances) <= 0:
			print "Failed to get instance IDs for %s-a" % args.environment
			sys.exit(-1)
		
		elb_health = False

		while(not elb_health):
			print "Have instance IDs, checking their health in the ELB (%s)..." % args.elb_name
			time.sleep(args.update_timeout)

			elb_instances = elb.describe_instance_health(LoadBalancerName=args.elb_name, Instances=active_instances)
			for instance in elb_instances["InstanceStates"]:
				if instance["State"] == "InService":
					elb_health = True
				else:
					elb_health = False

		if elb_health:
			asg.set_desired_capacity(AutoScalingGroupName="%s-b" % args.environment, DesiredCapacity=0)
			print "ASG %s-b is now draining..." % args.environment
		else:
			print "ELB health is not stable, so leaving ASG %s-b untouched" % args.environment

		print "Finished."

	else:
		print "No ASG is active"
		sys.exit(-1)

if __name__ == "__main__":
	sys.exit(main())
