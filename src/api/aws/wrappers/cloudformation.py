import boto3, botocore
import os
from commons.globals import ACCOUNT_ID, BUCKET_NAME, STACKSET_ID, CURRENT_REGION, DEPLOY_MODE
import time
from utils.logger_config import log
from rich.live import Live
from rich.table import Table
from rich.console import Console
from  botocore.exceptions import WaiterError
from aws.wrappers.s3 import S3Wrapper
from aws.wrappers.awsbase import AWSBase
# Ensure console can handle UTF-8 characters
import sys
# sys.stdout.reconfigure(encoding='utf-8')
console = Console()
class CloudFormation(AWSBase):
    def __init__(self, region_name='us-east-1'):
        super().__init__('cloudformation')
        self._cfn_outputs = None
        self.stack_name = 'bluearch-alerting-engine-cli-dev' if os.getenv('BLUEARCH_DEBUG') else 'bluearch-alerting-engine-cli'
        self._account_ids = None
        self.template_url = 'https://bluearch-templates.s3.amazonaws.com/local_cli_version/dev/alerting-engine-cli.yaml' if os.getenv('BLUEARCH_DEBUG') else 'https://bluearch-templates.s3.amazonaws.com/local_cli_version/alerting-engine-cli.yaml'
        self._region_name = region_name or CURRENT_REGION
        self._client = None  # Initialize _client to None

    # @property
    # def cfn_outputs(self):
    #     if self._cfn_outputs is None:
    #         self._cfn_outputs = CloudFormationOutputs()
    #     return self._cfn_outputs

    @property
    def main_account_id(self):
        return ACCOUNT_ID

    @property
    def region_name(self):
        return CURRENT_REGION

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client('cloudformation', region_name=self.region_name)
        return self._client

    @property
    def stackset_id(self):
        return STACKSET_ID

    @property
    def account_ids(self):
        if self._account_ids is None:
            if DEPLOY_MODE == 'manual':
                # Get account IDs from DB in manual mode
                from db.crud import DatabaseManager
                db = DatabaseManager()
                accounts = db.get_accounts_and_regions()
                self._account_ids = list(accounts.keys())
            else:
                # Get account IDs from stackset in auto mode
                self._account_ids = self.get_stackset_child_account_ids()
        return self._account_ids
    
    def get_stackset_child_account_ids(self):
        account_ids = [self.main_account_id]
        if self.stackset_id:
            paginator = self.client.get_paginator('list_stack_instances')
            response_iterator = paginator.paginate(StackSetName=self.stackset_id)
            for response in response_iterator:
                for instance in response['Summaries']:
                    if instance['StackInstanceStatus']['DetailedStatus'] == 'SUCCEEDED':
                        account_ids.append(instance['Account'])
        log.debug(f"Account IDs: {account_ids}")
        return account_ids

    def check_stack_exists(self) -> bool:
        try:
            self.client.describe_stacks(StackName=self.stack_name)
            return True
        except self.client.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'ValidationError':
                return False
            else:
                raise e

    def get_stack_resources(self):
        try:
            response = self.client.describe_stack_resources(StackName=self.stack_name)
            return response['StackResources']
        except self.client.exceptions.ClientError as e:
            if "does not exist" in str(e):
                return []
            else:
                raise

    def deploy_stack(self, org_id: str = None, workspace: str = None, auto_mode: str = 'yes'):
        mode = 'auto' if auto_mode == 'yes' else 'manual'
        console.print(f"[yellow]Creating stack '{self.stack_name}'...[/yellow]")
        parameters = [
            {
                'ParameterKey': 'DeploymentTargetOrganizationalUnitIds',
                'ParameterValue': org_id if org_id else ''
            },
            {
                'ParameterKey': 'Workspace',
                'ParameterValue': workspace
            },
            {
                'ParameterKey': 'DeployMode',
                'ParameterValue': mode
            }
        ]
                    
        return self.client.create_stack(
            StackName=self.stack_name,
            TemplateURL=self.template_url,
            Capabilities=['CAPABILITY_NAMED_IAM'],
            Parameters=parameters
        )

    def wait_for_stack_deletion(self, max_attempts: int = 120, delay: int = 30):
        try:
            waiter = self.client.get_waiter('stack_delete_complete')
            waiter.wait(
                StackName=self.stack_name,
                WaiterConfig={
                    'Delay': delay,
                    'MaxAttempts': max_attempts
                }
            )
            return True
        except botocore.exceptions.WaiterError as e:
            console.print(f"[red]Error waiting for stack deletion: {str(e)}[/red]")
            return False

    def delete_stack(self):
        try:
            s3 = S3Wrapper()
            console.print(f"[yellow]Emptying S3 bucket '{BUCKET_NAME}'...[/yellow]")
            s3.empty_bucket()
                        
            console.print(f"[yellow]Deleting stack '{self.stack_name}'. This may take a few minutes...[/yellow]")
            self.client.delete_stack(StackName=self.stack_name)

            self.monitor_stack_deletion()
            return self.wait_for_stack_deletion()
        except self.client.exceptions.ClientError as e:
            console.print(f"[red]Error deleting stack: {str(e)}[/red]")
            return False

    def wait_for_stack_instances_running(self, max_attempts: int = 120, delay: int = 30):
        if self.stackset_id is None:
            log.debug("Stackset ID not found. Skipping stack instances check.")
            return True                
        for attempt in range(1, max_attempts + 1):
            paginator = self.client.get_paginator('list_stack_instances')
            response_iterator = paginator.paginate(StackSetName=self.stackset_id)
            
            all_instances_running = True
            
            for response in response_iterator:
                for instance in response['Summaries']:
                    if instance['Status'] != 'CURRENT':
                        all_instances_running = False
                        console.print(f"[yellow]Stack instance '{instance['StackId']}' in account '{instance['Account']}' is in status '{instance['Status']}'.[/yellow]")
            
            if all_instances_running:
                console.print(f"[green]All stack instances of '{self.stack_name}' are in a running state.[/green]")
                return True
            
            if attempt == max_attempts:
                console.print(f"[yellow]Max attempts reached. Some stack instances of '{self.stack_name}' are not in a running state.[/yellow]")
                return False
            
            console.print(f"[yellow]Waiting for stack instances to be in a running state. Attempt {attempt}/{max_attempts}[/yellow]")
            time.sleep(delay)

    def check_stack_status(self, max_attempts: int = 120, delay: int = 30):
        try:
            waiter = self.client.get_waiter('stack_create_complete')
            waiter.wait(
                StackName=self.stack_name,
                WaiterConfig={
                    'Delay': delay,
                    'MaxAttempts': max_attempts
                }
            )
            console.print(f"Stack [green]'{self.stack_name}'[/green] created successfully!")        
            # Wait forall stack instances to be in a running state
            return self.wait_for_stack_instances_running(max_attempts=max_attempts, delay=delay)
        
        except botocore.exceptions.WaiterError as e:
            response = self.client.describe_stacks(StackName=self.stack_name)
            stack = response['Stacks'][0]
            stack_status = stack['StackStatus']
            stack_status_reason = stack.get('StackStatusReason', 'Unknown reason')
            console.print(f"[red]Stack '{self.stack_name}' creation failed. Reason: {stack_status_reason}[/red]")
            console.print(f"[red]Deleting stack '{self.stack_name}'. This may take a few minutes...[/red]")
            self.delete_stack()
            return False
        except Exception as e:
            if "does not exist" in str(e):
                log.info(f"Stack '{self.stack_name}' does not exist.")
                return False
            else:
                raise e

    def create_change_set(self):
        console = Console()
        try:
        # Retrieve the current stack parameters
            response = self.client.describe_stacks(StackName=self.stack_name)
            stack = response['Stacks'][0]
            parameters = stack['Parameters']

            # Retrieve the parameters from the new template
            template_parameters = self.get_template_parameters()

            # Transform the parameters into the expected format
            formatted_parameters = [
                {
                    'ParameterKey': param['ParameterKey'],
                    'UsePreviousValue': True
                }
                for param in parameters
                if param['ParameterKey'] in template_parameters
            ]

            # Create the change set with the new template and existing parameters
            try:
                create_response = self.client.create_change_set(
                    StackName=self.stack_name,
                    TemplateURL=self.template_url,
                    Parameters=formatted_parameters,
                    Capabilities=['CAPABILITY_NAMED_IAM'],
                    ChangeSetName=f'{self.stack_name}-change-set'
                )
            except self.client.exceptions.ClientError as e:
                if 'No updates are to be performed' in str(e):
                    console.print("[yellow]No changes detected in the new template. Skipping change set creation.[/yellow]")
                    return
                else:
                    console.print(f"[red]Error creating change set: {str(e)}[/red]")
                    raise
            except WaiterError as e:
                console.print(f"[red]Error waiting for change set creation: {str(e)}[/red]")
                
                # Retrieve and log additional details about the change set
                try:
                    describe_response = self.client.describe_change_set(
                        ChangeSetName=f'{self.stack_name}-change-set',
                        StackName=self.stack_name
                    )
                    console.print(f"Change set details: {describe_response}")
                except Exception as e:
                    console.print(f"[red]Error retrieving change set details: {str(e)}[/red]")
                
                raise

        except self.client.exceptions.AlreadyExistsException:
            console.print("[yellow]The change set already exists. Proceeding with the existing change set.[/yellow]")
        except self.client.exceptions.InsufficientCapabilitiesException:
            console.print("[red]Insufficient capabilities to create the change set. Update aborted.[/red]")
            raise
        except self.client.exceptions.LimitExceededException:
            console.print("[red]Change set limit exceeded. Update aborted.[/red]")
            raise

    def get_template_parameters(self):
        # Retrieve the parameters from the new template
        response = self.client.get_template_summary(TemplateURL=self.template_url)
        template_parameters = [param['ParameterKey'] for param in response.get('Parameters', [])]
        return template_parameters
    
    def describe_change_set(self):
        console = Console()
        try:
            # Wait for the change set to be created
            waiter = self.client.get_waiter('change_set_create_complete')
            waiter.wait(
                ChangeSetName=f'{self.stack_name}-change-set',
                StackName=self.stack_name,
                WaiterConfig={
                    'Delay': 5,
                    'MaxAttempts': 6
                }
            )

            # Describe the change set
            response = self.client.describe_change_set(
                StackName=self.stack_name,
                ChangeSetName=f'{self.stack_name}-change-set'
            )
            self.display_change_set(response)
            return response

        except WaiterError as e:
            if "The submitted information didn't contain changes." in str(e):
                console.print("[yellow]No updates found in the changeset.[/yellow]")
            return None

    def execute_change_set(self):
        console = Console()
        try:
            self.client.execute_change_set(
                StackName=self.stack_name,
                ChangeSetName=f'{self.stack_name}-change-set'
            )
        except self.client.exceptions.ChangeSetNotFoundException:
            console.print("[red]The specified change set does not exist.[/red]")
            raise

    def wait_for_change_set(self, timeout=300, delay=5):
        try:
            waiter = self.client.get_waiter('stack_update_complete')
            waiter.wait(
                StackName=self.stack_name,
                WaiterConfig={
                    'Delay': delay,
                    'MaxAttempts': timeout // delay
                }
            )
            return "UPDATE_COMPLETE"
        except WaiterError as e:
            if "Waiter encountered a terminal failure state" in str(e):
                response = self.client.describe_stacks(StackName=self.stack_name)
                stack_status = response['Stacks'][0]['StackStatus']
                if stack_status == "UPDATE_ROLLBACK_COMPLETE":
                    return "UPDATE_ROLLBACK_COMPLETE"
                elif stack_status == "UPDATE_ROLLBACK_FAILED":
                    return "UPDATE_ROLLBACK_FAILED"
                else:
                    return "UPDATE_FAILED"
            else:
                raise

    def delete_change_set(self):
        console = Console()
        try:
            self.client.delete_change_set(
                StackName=self.stack_name,
                ChangeSetName=f'{self.stack_name}-change-set'
            )
        except self.client.exceptions.ChangeSetNotFoundException:
            console.print("[yellow]The specified change set does not exist. Skipping deletion.[/yellow]")
            
    def display_change_set(self, change_set):
        console = Console()
        table = Table(title="Change Set Details", show_header=True, header_style="bold magenta", show_lines=True)
        
        # Add columns to the table
        table.add_column("Property", style="cyan")
        table.add_column("Value")

        table.add_row("Change Set Name", change_set['ChangeSetName'])
        table.add_row("Stack Name", change_set['StackName'])
        table.add_row("Execution Status", change_set['ExecutionStatus'])
        table.add_row("Status", change_set['Status'])
        table.add_row("Creation Time", str(change_set['CreationTime']))

        if 'StatusReason' in change_set:
            table.add_row("Status Reason", change_set['StatusReason'])

        table.add_row("Capabilities", ", ".join(change_set.get('Capabilities', [])))

        changes_table = Table(title="Changes", show_header=True, header_style="bold magenta", show_lines=True)
        
        # Add columns to the changes_table
        changes_table.add_column("Action", style="cyan")
        changes_table.add_column("Logical ID")
        changes_table.add_column("Physical ID")
        changes_table.add_column("Resource Type")
        changes_table.add_column("Replacement")
        changes_table.add_column("Scope")

        for change in change_set.get('Changes', []):
            resource_change = change['ResourceChange']
            changes_table.add_row(
                resource_change['Action'],
                resource_change['LogicalResourceId'],
                resource_change.get('PhysicalResourceId', ''),
                resource_change['ResourceType'],
                str(resource_change.get('Replacement', '')),
                ", ".join(resource_change.get('Scope', []))
            )

        console.print(table)
        console.print(changes_table)

    def monitor_stack_creation(self):
        try:
            with Live(console=console, refresh_per_second=1) as live:
                stack_complete = False
                while not stack_complete:
                    stack_status = self.get_stack_status()
                    resources = self.get_stack_resources()
                    if resources:
                        live.update(self.generate_resource_table(resources=resources, operation="creation", stack_status=stack_status))
                        stack_complete = stack_status in ['CREATE_COMPLETE', 'CREATE_FAILED', 'ROLLBACK_COMPLETE']
                    else:
                        live.update(Table(title="Waiting for create resources..."))
                    time.sleep(5)

            final_status = "succeeded" if stack_status == 'CREATE_COMPLETE' else "failed"
            console.print(f"\n[bold]{'=' * 20}[/bold]")
            console.print(f"[bold]Stack create {final_status}[/bold]")
            console.print(f"[bold]Final status: {stack_status}[/bold]")
            console.print(f"[bold]{'=' * 20}[/bold]")
        except Exception as e:
            console.print(f"[red]Error monitoring stack creation: {str(e)}[/red]")

    def monitor_stack_update(self, change_set_response):
        change_set_resources = self.capture_initial_resource_states(change_set_response)
        self.persisted_updated_resources = {}

        with Live(console=console, refresh_per_second=1) as live:
            update_complete = False
            while not update_complete:
                stack_status = self.get_stack_status()
                resources = {r['LogicalResourceId']: r for r in self.get_stack_resources()}
                
                updated = self.track_resource_state_changes(resources, change_set_resources)
                live.update(self.generate_resource_table(resources=updated, operation="update", stack_status=stack_status))
                
                if stack_status in ['UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE', 'UPDATE_FAILED']:
                    update_complete = True
                
                time.sleep(5)

        final_status = "succeeded" if stack_status == 'UPDATE_COMPLETE' else "failed"
        console.print(f"\n[bold]{'=' * 20}[/bold]")
        console.print(f"[bold]Stack update {final_status}[/bold]")
        console.print(f"[bold]Final status: {stack_status}[/bold]")
        console.print(f"[bold]{'=' * 20}[/bold]")

    def monitor_stack_deletion(self):
        try:
            with Live(console=console, refresh_per_second=1) as live:
                stack_deleted = False
                consecutive_not_exist_errors = 0
                max_not_exist_errors = 3  # Adjust this value as needed

                while not stack_deleted:
                    try:
                        stack_status = self.get_stack_status()
                        resources = self.get_stack_resources()
                        
                        if resources:
                            live.update(self.generate_resource_table(resources=resources, operation="delete"))
                            consecutive_not_exist_errors = 0  # Reset the counter
                        else:
                            live.update(Table(title="Waiting for resource deletion..."))
                        
                        if stack_status in ['DELETE_COMPLETE', 'DELETE_FAILED']:
                            stack_deleted = True

                    except self.client.exceptions.ClientError as e:
                        if "does not exist" in str(e):
                            consecutive_not_exist_errors += 1
                            if consecutive_not_exist_errors >= max_not_exist_errors:
                                console.print("[green]Stack deletion completed.[/green]")
                                stack_deleted = True
                            else:
                                live.update(Table(title=f"Stack deletion in progress... (Checking: {consecutive_not_exist_errors}/{max_not_exist_errors})"))
                        else:
                            raise
                    
                    time.sleep(5)

            console.print(f"\n[bold]{'=' * 20}[/bold]")
            console.print(f"[bold]Stack deleted[/bold]")
            console.print(f"[bold]Final status: DELETE_COMPLETE[/bold]")
            console.print(f"[bold]{'=' * 20}[/bold]")
        except Exception as e:
            console.print(f"[red]Error monitoring stack deletion: {str(e)}[/red]")

    def get_stack_status(self):
        try:
            response = self.client.describe_stacks(StackName=self.stack_name)
            return response['Stacks'][0]['StackStatus']
        except self.client.exceptions.ClientError as e:
            if "does not exist" in str(e):
                return "DELETE_COMPLETE"
            else:
                raise

    def capture_initial_resource_states(self, change_set_response) -> dict:
        initial_resources = {}
        changesets = change_set_response
        resources = self.get_stack_resources()
        changes = changesets['Changes']

        for change in changes:
            if change['ResourceChange']['Action'] == 'Add':
                initial_resources[change['ResourceChange']['LogicalResourceId']] = {
                    'ResourceStatus': 'CREATE_PENDING',
                    'ResourceType': change['ResourceChange']['ResourceType']
                }

            for resource in resources:
                if change['ResourceChange']['LogicalResourceId'] == resource['LogicalResourceId']:
                    initial_resources[resource['LogicalResourceId']] = {
                        'ResourceStatus': resource['ResourceStatus'],
                        'ResourceType': resource['ResourceType']
                    }
        return initial_resources

    def track_resource_state_changes(self, current_resources, initial_resources) -> dict:
        for logical_id, resource in current_resources.items():
            if logical_id in initial_resources:
                if (resource['ResourceStatus'] != initial_resources[logical_id]['ResourceStatus'] or
                        logical_id in self.persisted_updated_resources):
                    self.persisted_updated_resources[logical_id] = resource

        for logical_id in initial_resources:
            if logical_id not in current_resources:
                self.persisted_updated_resources[logical_id] = {
                    'ResourceStatus': 'DELETE_COMPLETE',
                    'ResourceType': initial_resources[logical_id]['ResourceType']
                }

        return self.persisted_updated_resources

    def generate_resource_table(self, resources=None, operation='create', stack_status=None):
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Logical ID", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Status", style="magenta")

        if resources:
            if operation == 'update':
                for logical_id, resource in resources.items():
                    status = resource['ResourceStatus']
                    status_style = "green" if "COMPLETE" in status else "yellow" if "IN_PROGRESS" in status else "red"

                    table.add_row(
                        logical_id,
                        resource['ResourceType'],
                        f"[{status_style}]{status}[/{status_style}]"
                    )
            else:
                for resource in resources:
                    status = resource.get('ResourceStatus', 'Unknown')
                    if operation == 'delete':
                        status_style = "green" if "DELETE_COMPLETE" in status else "yellow" if "IN_PROGRESS" in status else "red"
                    elif operation == 'create': 
                        status_style = "green" if "CREATE_COMPLETE" in status else "yellow" if "IN_PROGRESS" in status else "red"
                    else:
                        status_style = "green" if "COMPLETE" in status else "yellow" if "IN_PROGRESS" in status else "red"

                    table.add_row(
                        resource.get('LogicalResourceId', 'Unknown'),
                        resource.get('ResourceType', 'Unknown'),
                        f"[{status_style}]{status}[/{status_style}]"
                    )
        else:
            table.add_row("No resources left", "", "")

        if stack_status:
            table.title = f"Stack Status: {stack_status}"

        return table
    