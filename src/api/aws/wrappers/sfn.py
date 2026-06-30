# Standard library imports
import json
import time
import boto3
from datetime import datetime
from queue import Queue
from threading import Thread, Event
from collections import deque
from botocore.exceptions import ClientError
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.text import Text
from utils.logger_config import log
from aws.wrappers.awsbase import AWSBase
from commons.get import get_accounts_and_regions
from commons.resource_actions import RESOURCE_ACTIONS
from commons.globals import CURRENT_REGION, WORKSPACE, ACCOUNT_ID, STATE_MACHINE_ARN
import re
import tempfile
import os
import sys
# Ensure console can handle UTF-8 characters
sys.stdout.reconfigure(encoding='utf-8')

class StateMachine(AWSBase):
    """Encapsulates Step Functions state machine actions."""
    MAX_PAYLOAD_SIZE = 256 * 1024  # 256 KB in bytes

    def __init__(self):
        """
        :param client: A Boto3 Step Functions client.
        """
        super().__init__('stepfunctions')
        self.region_name = CURRENT_REGION
        self.workspace = WORKSPACE
        self.account_id = ACCOUNT_ID
        self.state_machine_arn = STATE_MACHINE_ARN
        
    def _generate_populate_input(self, account_ids: list = None, resources: list = None, regions: list = None):
        # Defaulting to all accounts and resources if any are not provided
        if account_ids is None and regions is None:
            accounts_and_regions = get_accounts_and_regions()
        elif account_ids is not None:
            accounts_and_regions = get_accounts_and_regions(account_ids)
        else:
            accounts_and_regions = get_accounts_and_regions()

        if resources is None:
            resources = list(RESOURCE_ACTIONS.keys())

        payload_items = []
        for account_id, account_info in accounts_and_regions.items():
            if regions is not None:
                filtered_regions = [region for region in account_info['regions'] if region in regions]
            else:
                filtered_regions = account_info['regions']
            if filtered_regions:
                payload_item = {
                    "WORKFLOW": "POPULATE",
                    "ACCOUNT_ID": account_id,
                    "ACCOUNT_NAME": account_info['account_name'],
                    "REGION_NAME": filtered_regions,
                    "RESOURCE_ACTIONS": resources,
                    "TELEMETRY_CONFIG": {
                        "source": "bluearch-core",
                        "schema_version": "event.v1",
                    }
                }
                payload_items.append(payload_item)

        payload = {
            "PAYLOAD": payload_items
        }
        log.debug(json.dumps(payload, indent=2))
        return payload

    def wait_for_execution(self, execution_arn, poll_interval=1):
        """Wait for the execution to complete and display progress and logs."""
        execution_status = 'RUNNING'
        console = Console()
        execution_name = execution_arn.split(':')[-1]
        cloudwatch_logs_client = boto3.client('logs', region_name=self.region_name)

        # Create a temporary file for logging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = os.path.join(tempfile.gettempdir(), f"BlueArch_Execution_{timestamp}.log")
        
        with open(log_file_path, 'w') as log_file:
            log_file.write(f"Execution log for {execution_name}\n")
            log_file.write(f"Started at: {datetime.now()}\n\n")

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn()
        )
        task = progress.add_task(f"Execution {execution_name}", total=None)

        layout = Layout()
        layout.split(
            Layout(Panel(progress), size=3),
            Layout(Panel("", title="Logs", height=console.height - 5), name="logs")
        )

        log_queue = Queue()
        stop_event = Event()
        log_thread = Thread(target=self._tail_logs, args=(cloudwatch_logs_client, log_queue, stop_event))
        log_thread.daemon = True
        log_thread.start()

        recent_logs = []

        with Live(layout, refresh_per_second=4, console=console) as live:
            while execution_status in ['RUNNING', 'STARTING']:
                try:
                    response = self.client.describe_execution(executionArn=execution_arn)
                    execution_status = response['status']
                    
                    while not log_queue.empty():
                        log_message = log_queue.get_nowait()
                        recent_logs.append(log_message)
                        with open(log_file_path, 'a') as log_file:
                            log_file.write(f"{log_message}\n")
                    
                    # Keep only the most recent logs that fit in the panel
                    max_logs = console.height - 8  # Adjust this value as needed
                    if len(recent_logs) > max_logs:
                        recent_logs = recent_logs[-max_logs:]
                    
                    layout["logs"].update(Panel("\n".join(recent_logs), title="Logs", height=console.height - 5))
                    
                    time.sleep(poll_interval)
                except ClientError as err:
                    console.print(f"[bold red]Couldn't describe execution {execution_name}: {err}[/bold red]")
                    raise

        # Signal the log tailing thread to stop
        stop_event.set()
        log_thread.join(timeout=5)

        # Ensure we get any remaining logs after the execution has completed
        while not log_queue.empty():
            log_message = log_queue.get_nowait()
            recent_logs.append(log_message)
            with open(log_file_path, 'a') as log_file:
                log_file.write(f"{log_message}\n")

        # Keep only the most recent logs that fit in the panel
        max_logs = console.height - 8
        if len(recent_logs) > max_logs:
            recent_logs = recent_logs[-max_logs:]

        layout["logs"].update(Panel("\n".join(recent_logs), title="Final Logs", height=console.height - 5))
        progress.update(task, description=f"Execution {execution_name} - Status: {execution_status}")

        with open(log_file_path, 'a') as log_file:
            log_file.write(f"\nExecution ended at: {datetime.now()}\n")
            log_file.write(f"Final status: {execution_status}\n")

        console.print(f"Full execution log saved to: {log_file_path}")
        return execution_status

    def _tail_logs(self, cloudwatch_logs_client, log_queue, stop_event):
        """Tail the logs using CloudWatch Logs API and add them to the queue."""
        try:
            log_group_arn = f"arn:aws:logs:{self.region_name}:{self.account_id}:log-group:/aws/stepfunctions/{self.workspace}-bluearch-alerting-engine"
            
            log_queue.put(f"Attempting to tail logs for group: {log_group_arn}")
            
            response = cloudwatch_logs_client.start_live_tail(logGroupIdentifiers=[log_group_arn])
            event_stream = response['responseStream']
            
            for event in event_stream:
                if stop_event.is_set():
                    event_stream.close()
                    break
                
                if 'sessionStart' in event:
                    log_queue.put("Log tailing session started")
                elif 'sessionUpdate' in event:
                    log_events = event['sessionUpdate']['sessionResults']
                    for log_event in log_events:
                        log_stream_name = log_event['logStreamName']
                        message = log_event['message']
                        timestamp = datetime.fromtimestamp(log_event['timestamp']/1000)

                        formatted_log = Text()
                        if log_stream_name.startswith(f"{self.workspace}-bluearch-alerting-engine"):
                            # Application logs
                            if not message.startswith("awslimitchecker") and not message.startswith("_distutils_hack/__init__"):
                                formatted_log.append(f"[{timestamp}] {message}")
                                log_queue.put(str(formatted_log))
                        elif log_stream_name.startswith("states/"):
                            # State machine logs
                            try:
                                log_data = json.loads(message)
                                if "type" in log_data:
                                    step_parts = re.findall('[A-Z][^A-Z]*', log_data['type'])
                                    formatted_log.append(f"[{timestamp}] - State Machine Stage: {' '.join(step_parts)}", style="green")
                                    log_queue.put(str(formatted_log))
                            except json.JSONDecodeError:
                                # If it's not valid JSON, ignore this log
                                pass
                else:
                    # On-stream exceptions are captured here
                    raise RuntimeError(str(event))

        except ClientError as e:
            error_message = f"Error tailing CloudWatch logs: {e}"
            log.error(error_message)
            log_queue.put(error_message)
        except Exception as e:
            error_message = f"Unexpected error in _tail_logs: {e}"
            log.error(error_message)
            log_queue.put(error_message)
        finally:
            log_queue.put("Log tailing has ended.")

    def start(self, run_input):
        # Convert run_input to JSON string to check size
        run_input_str = json.dumps(run_input)
        if len(run_input_str.encode('utf-8')) <= self.MAX_PAYLOAD_SIZE:
            # If payload is within size limit, start execution
            execution_arn = self._start_execution(run_input_str)
            final_status = self.wait_for_execution(execution_arn)
            console = Console()
            console.print(f"Execution [bold]{execution_arn.split(':')[-1]}[/bold] completed with status: [green]{final_status}[/green]")
            return execution_arn
        else:
            # If payload exceeds size limit, split and start multiple executions
            execution_arns = []
            # Example split strategy: split by top-level keys assuming it's a dictionary
            # This part needs customization based on actual payload structure
            for key, value in run_input.items():
                chunk = json.dumps({key: value})
                if len(chunk.encode('utf-8')) > self.MAX_PAYLOAD_SIZE:
                    raise ValueError(f"Chunk for key {key} exceeds the maximum Step Functions input size.")
                execution_arn = self._start_execution(chunk)
                final_status = self.wait_for_execution(execution_arn)
                console = Console()
                console.print(f"Execution [bold]{execution_arn.split(':')[-1]}[/bold] completed with status: [green]{final_status}[/green]")
                execution_arns.append(execution_arn)
            return execution_arns

    def _start_execution(self, payload):
        """Helper method to start a single execution of the state machine."""
        try:
            response = self.client.start_execution(
                stateMachineArn=self.state_machine_arn,
                input=payload
            )
            execution_arn = response["executionArn"]
            console = Console()
            url = Text(f"https://{self.region_name}.console.aws.amazon.com/states/home?region={self.region_name}#/executions/details/{execution_arn}")
            url.stylize("bold blue")
            console.print(f"Started execution. You can check at the link below: \n{url}\n")
            return execution_arn
        except ClientError as err:
            console = Console()
            console.print(f"[bold red]Couldn't start state machine execution: {err}[/bold red]")
            raise
    def populate(self, account_ids: list = None, resources: list = None):
        """Start a 'POPULATE' state machine execution."""
        payload = self._generate_populate_input(account_ids, resources)
        log.debug(json.dumps(payload, indent=2))
        return self.start(payload)
    
    def check_previous_execution(self):
        try:
            last_execution = self.client.list_executions(
                stateMachineArn=self.state_machine_arn,
                statusFilter='SUCCEEDED',
                maxResults=1
            )
            payload = self.client.describe_execution(executionArn=last_execution['executions'][0]['executionArn'])
            return payload
        except IndexError:
            log.debug("No previous execution found.")
            return None
