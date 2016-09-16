
import boto3
import argparse
import sys
import time
import math

asg = boto3.client("autoscaling")
elb = boto3.client("elb")

def current_instance_count(group_name):
	pass

def check_instance_health(instance_id):
	pass

def check_backend_health(elb_name, instance_id):
	pass

def scale_application(elb, args, up, down):
	asg.set_desired_capacity(AutoScalingGroupName="%s-%s" % (args.environment, up), DesiredCapacity=args.instance_count)
	asg_instances = []
	asg_health = False

	while(not asg_health):
		print "Have %s-%s ramping up, checking instance health..." % (args.environment, up)
		time.sleep(args.update_timeout)

		asg_instances = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-%s" % (args.environment, up)])["AutoScalingGroups"][0]["Instances"]
		for instance in asg_instances:
			if instance["LifecycleState"] == "InService":
				asg_health = True
			else:
				asg_health = False

	active_instances = [{"InstanceId": x["InstanceId"]} for x in asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-%s" % (args.environment, up)])["AutoScalingGroups"][0]["Instances"]]
	
	if len(active_instances) <= 0:
		print "Failed to get instance IDs for %s-%s" % (args.environment, up)
		sys.exit(-1)
	
	elb_health = False
	health_check_start = time.time()
	while(not elb_health):
		print "Have instance IDs, checking their health in the ELB (%s)..." % args.elb_name
		time.sleep(args.update_timeout)

		elb_instances = elb.describe_instance_health(LoadBalancerName=args.elb_name, Instances=active_instances)
		for instance in elb_instances["InstanceStates"]:
			if instance["State"] == "InService":
				elb_health = True
			else:
				elb_health = False


		if int(math.ceil(time.time() - health_check_start)) >= args.health_check_timeout:
			break

	if elb_health:
		asg.set_desired_capacity(AutoScalingGroupName="%s-%s" % (args.environment, down), DesiredCapacity=0)
		print "ASG %s-%s is now draining..." % (args.environment, down)
		print "Finished, without issues."
	else:
		print "ELB health is not stable, so leaving both ASGs untouched."
		print "Finished, but with issues."

def main():
	parser = argparse.ArgumentParser(description='Build Data to S3')
	parser.add_argument("--dry-run", dest="dryrun", help="Only detect what we would do; don't run anything", action='store_true', required=False)
	parser.add_argument("--environment", dest="environment", help="The environment to A/B deploy against", required=True)
	parser.add_argument("--elb-name", dest="elb_name", help="The ELB to which your ASG is linked", required=True)
	parser.add_argument("--instance-count", dest="instance_count", help="How many instances you want tho ASG to grow by (default: 2)", required=False, type=int, default=2)
	parser.add_argument("--update-timeout", dest="update_timeout", help="How long to wait between API calls/console updates (default: 30s)", required=False, type=int, default=10)
	parser.add_argument("--health-check-timeout", dest="health_check_timeout", help="How long to wait for the health of an ELB to stabilse (default: 300s/5m)", required=False, type=int, default=300)
	args = parser.parse_args()

	environment_a = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-a" % args.environment])
	environment_b = asg.describe_auto_scaling_groups(AutoScalingGroupNames=["%s-b" % args.environment])

	if (environment_a["AutoScalingGroups"][0]["DesiredCapacity"] == 0) and (environment_b["AutoScalingGroups"][0]["DesiredCapacity"] == 0):
		print "No active ASG; starting with 'a'"
		if not args.dryrun:
			scale_application(args, "a", "b")

	elif environment_a["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
		print "Currently active ASG is %s-a" % args.environment
		if not args.dryrun:
			scale_application(args, "b", "a")	

	elif environment_b["AutoScalingGroups"][0]["DesiredCapacity"] > 0:
		print "Currently active ASG is %s-b" % args.environment
		if not args.dryrun:
			scale_application(args, "a", "b")

if __name__ == "__main__":
	sys.exit(main())
