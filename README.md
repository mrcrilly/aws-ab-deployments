# A/B Deployment Tool
Performs A/B deployment tasks for us by scaling ASGs and then checking for health instances and finally healthy ELB pool members.

## Usage
The tool is designed to be used from the CLI. It could probably be converted to an API Gateway architecture with a day's work, allowing it to act as an API.

Here is the CLI argument list:
```
-h, --help            show this help message and exit
--single-asg          Deploy to a single ASG - no A/B process - only if it's
                    empty.
--dry-run             Only detect what we would do; don't run anything
--zero                Zero the currently active ASG
--environment ENVIRONMENT
                    The environment to A/B deploy against
--elb-name ELB_NAME   The ELB to which your ASG is linked
--instance-count-match
                    Match the new ASG instance count against the existing
                    ASG
--instance-count INSTANCE_COUNT
                    How many instances you want tho ASG to grow by
                    (default: 8)
--instance-count-step INSTANCE_COUNT_STEP
                    How many instances to scale by at a time (default: 8)
--update-timeout UPDATE_TIMEOUT
                    How long to wait between API calls/console updates
                    (default: 30s)
--health-check-timeout HEALTH_CHECK_TIMEOUT
                    How long to wait for the health of an ELB to stabilse
                    (default: 600s/10m)
--clean-up            Clean up existing ASGs if they ahve instances. Very
                    dangerous option! (default: false)
--verbose             Print messages about progress and what step we're at
                    (default: false)
```

### Common Uses
This is a list of common command line combinations, and their effects.

- `python main.py --environment qa --elb-name qa-external --verbose`
-- A standard **eight** node A/B deployment, printing out all messages to STDOUT;