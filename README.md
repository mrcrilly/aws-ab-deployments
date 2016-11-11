# A/B Deployment Tool
Performs A/B deployment tasks for you by scaling ASGs and then checking for healthly instances and finally healthy ELB pool members.

## Assumptions
- The AWS infrastructure is already operational;
- ASGs and ELBs as used for the application deployment model/architecture;
- You have two ELBs per environment: A and B;
- ELB names are in an `$ENVIRONMENT-a` and `$ENVIRONMENT-b` schema;

## Usage
The tool is designed to be used from the CLI. It could probably be converted to an API Gateway architecture with a day's work, allowing it to act as an API, but this will come later.

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

- `python main.py --environment qa --elb-name qa-public --verbose`: a standard **eight** node A/B deployment, printing out all messages to STDOUT;
- `python main.py --environment qa --elb-name qa-public --instance-count 4`: quietly A/B QA, bringing up four nodes instead of the default eight;
- `python main.py --environment selenium --single-asg`: our jMeter ASG doesn't have a "B" counterpart, so the `--single-asg` flag just refreshes the ASG name provided to `--environment`;
- `python main.py --environment development --zero`: essentially burn down the environment, reducing the active ASG to `0` instances;

## Process
These are the processes the A/B Deployment script runs through when executed:

### When `--environment` and `--elb-name` are provided:
1. Check the environment lock isn't in place. If it is not, continue, otherwise halt execution;
1. Gets information on ASG "A" and "B";
1. Checks to ensure they don't **both** contain instances. If they do, execution halts as the tool isn't to know which ASG to clear, if any;
1. Checks to see what ASG currently has instances it in, and populates the opposite to that with the (default) value of `--instance-count`;
1. After populating the ASG, it waits for the instances to come live;
1. Then it checks the instances in the ELB pool to ensure they come healthy;
1. When they do, the originally populate ASG is then drained by simply setting its `desired` state to `0`;

### When `--environment` and `--zero` are provided:
1. Check the environment lock isn't in place. If it is not, continue, otherwise halt execution;
1. Gets information on ASG "A" and "B";
1. If they're both empty, stop execution as there is nothing to "zero";
1. Checks to ensure they don't **both** contain instances. If they do, execution halts as the tool isn't to know which ASG to clear, if any;
1. Otherwise it will simply drain down the active ASG by setting `desired` to `0`;

### When `--environment` and `--single-asg` are provided:
1. Usual checks, as above;
1. Uses value from `--environment` as the ASG name, and no `-a` or `-b` is appended;
1. Does the normal scale down process, as above, of the ASG if it's active/populated;
