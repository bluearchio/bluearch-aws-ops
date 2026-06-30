import boto3
import re
from botocore.exceptions import ClientError, WaiterError
from aws.wrappers.cloudformation import CloudFormation
from rich.console import Console
from rich.prompt import Prompt
from aws.wrappers.awsbase import AWSBase
import sys

# Ensure console can handle UTF-8 characters
sys.stdout.reconfigure(encoding='utf-8')

console = Console()
class EventBridge(AWSBase):
    def __init__(self):
        super().__init__('events')
        self.cloudformation = CloudFormation()
        self._rule_name = None
        self._stack_name = None

    @property
    def rule_name(self) -> str:
        if self._rule_name is None:
            resources = self.cloudformation.get_stack_resources()
            for resource in resources:
                if resource['LogicalResourceId'] == 'SchedulerEventBridgeRule':
                    self._rule_name = resource['PhysicalResourceId']
                    break
        return self._rule_name
    
    @property
    def stack_name(self) -> str:
        return self.cloudformation.stack_name

    def GetScheduleExpression(self) -> str:
        try:
            response = self.client.describe_rule(
                Name = self.rule_name
            )
            return response['ScheduleExpression']
        except ClientError as e:
            console.print(f"[red]Error getting the schedule expression from the Event Bridge Rule: {str(e)}[/red]")

    def GetScheduleStatus(self) -> str:
        try:
            response = self.client.describe_rule(
                Name = self.rule_name
            )
            return response['State']
        except ClientError as e:
            console.print(f"[red]Error getting the schedule expression from the Event Bridge Rule: {str(e)}[/red]")

    def SetScheduleExpression(self, schedule_expression: str="1200 days", status: str="DISABLED") -> dict:
        try:
            while True:
                try:
                    valid, expression = self.ValidateScheduleExpression(schedule_expression)
                    if not valid:
                        raise ValueError()
                    break
                except re.error as e:
                    console.print(f"[red]Regex substitution error: {str(e)}. Please try again.[/red]")
                    schedule_expression = Prompt.ask("[blue]Enter the desired rate time of your scheduler[/blue]")
                except ValueError:
                    console.print(f"[red]You inserted an invalid rate expression, check the example table and try again.[/red]")
                    schedule_expression = Prompt.ask("[blue]Enter the desired rate time of your scheduler[/blue]")

            stack_response = self.cloudformation.client.describe_stacks(StackName=self.stack_name)
            current_parameters = {param['ParameterKey']: param['ParameterValue'] for param in stack_response['Stacks'][0]['Parameters']}

            current_parameters['SchedulerExpression'] = f"rate({expression})"
            current_parameters['SchedulerState'] = status

            parameters = [{'ParameterKey': k, 'ParameterValue': v} for k, v in current_parameters.items()]

            update_result = self.cloudformation.client.update_stack(
                StackName=self.stack_name,
                UsePreviousTemplate=True,
                Parameters=parameters,
                Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']
            )

            stack_id = update_result["StackId"]
            waiter = self.cloudformation.client.get_waiter('stack_update_complete')
            waiter.wait(StackName=stack_id, WaiterConfig={'Delay': 5, 'MaxAttempts': 10})

            return self.GetScheduleExpression()
        except (ClientError, WaiterError) as e:
            if "No updates are to be performed" in str(e):
                console.print("[yellow]The rate expression and status are the same as the current ones.\nThere are no updates to be performed.[/yellow]")
            else:
                console.print(f"[red]Error trying to create the scheduler job: {str(e)}[/red]")
                raise

    def ValidateScheduleExpression(self, schedule_expression: str) -> tuple[bool, str]:
        pattern = r'^(\d+)\s+(\w+)$'
        match = re.match(pattern, schedule_expression)

        if not match:
            return False, ""
        
        value, unit = match.groups()
        value = int(value)

        if value <= 0:
            return False, ""

        valid_units = {
            'minute': 'minutes',
            'hour': 'hours',
            'day': 'days'
        }

        if unit not in valid_units and unit not in valid_units.values():
            return False, ""
        
        if value == 1:
            correct_unit = unit.rstrip('s')
        else:
            correct_unit = valid_units.get(unit.rstrip('s'), unit)

        corrected_expression = f"{value} {correct_unit}"

        return True, corrected_expression