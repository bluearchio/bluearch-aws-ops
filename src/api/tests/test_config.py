import pytest
from typer.testing import CliRunner
from bluearch import cli_app
import requests
import pathlib

runner = CliRunner()

@pytest.mark.parametrize("input_data, expected_output, expect_delete", [
    ("yes\n", "CloudFormation stack deleted successfully", True),
    ("no\n", "Stack deletion aborted.", False)
])
def test_delete_stack_confirmation(mocker, input_data, expected_output, expect_delete):
    """Test delete command with confirmation"""
    # Mock the CloudFormation wrapper
    mock_cf = mocker.patch('aws.wrappers.cloudformation.CloudFormation')
    mock_cf_instance = mock_cf.return_value
    mock_cf_instance.check_stack_exists.return_value = True
    mock_cf_instance.delete_stack.return_value = True

    # Invoke the CLI command with simulated input
    result = runner.invoke(
        cli_app,
        ["delete"],
        input=input_data,
        prog_name="bluearch"
    )

    # Assertions
    assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
    assert expected_output in result.stdout
    if expect_delete:
        mock_cf_instance.delete_stack.assert_called_once()
    else:
        mock_cf_instance.delete_stack.assert_not_called()

def test_deploy_with_valid_inputs(mocker):
    """Test deploy command with valid inputs"""
    # Mock the CloudFormation wrapper
    mock_cf = mocker.patch('aws.wrappers.cloudformation.CloudFormation')
    mock_cf_instance = mock_cf.return_value
    mock_cf_instance.check_stack_exists.return_value = False
    mock_cf_instance.deploy_stack.return_value = True
    mock_cf_instance.check_stack_status.return_value = True
    mock_cf_instance.get_cfn_outputs.return_value = {
        'RoleName': 'test-role',
        'AccTableName': 'test-acc-table',
        'RecTableName': 'test-rec-table',
        'Region': 'us-east-1'
    }
    
    # Mock cache operations
    mock_cache = mocker.patch('utils.cache_manager.CLOUDFORMATION_CACHE')
    
    # Mock database operations
    mock_db = mocker.patch('db.crud.DatabaseManager')
    mock_db_instance = mock_db.return_value
    
    # Mock role validation
    mock_clients = mocker.patch('aws.wrappers.clients.AWSClients')
    mock_clients.validate_manual_deployment_role_assumptions.return_value = [
        ('123456789012', True)
    ]
    
    # Mock Organizations check
    mock_org = mocker.patch('aws.wrappers.organizations.Organizations')
    mock_org_instance = mock_org.return_value
    mock_org_instance.is_account_delegated_admin_or_management.return_value = True
    
    # Simulate user inputs in the correct order:
    # 1. Auto mode prompt (yes)
    # 2. Workspace name (must be lowercase letters only)
    # 3. Org ID
    # 4. Final confirmation
    simulated_input = "yes\nworkspace\nou-1234-12345678\nyes\n"
    
    result = runner.invoke(
        cli_app,
        ["deploy"],
        input=simulated_input,
        prog_name="bluearch"
    )
    
    # Print output for debugging if test fails
    if result.exit_code != 0:
        print(f"Test failed with output:\n{result.stdout}")
        if result.exception:
            print(f"Exception: {result.exception}")
    
    # Assertions
    assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
    assert "Deploy completed!" in result.stdout
    mock_cf_instance.deploy_stack.assert_called_once_with(
        org_id="ou-1234-12345678", 
        workspace="workspace",
        auto_mode="yes"
    )
    mock_cf_instance.check_stack_status.assert_called_once()

def test_deploy_manual_mode(mocker, mock_manual_instructions):
    """Test deploy command in manual mode"""
    # Mock the CloudFormation wrapper
    mock_cf = mocker.patch('aws.wrappers.cloudformation.CloudFormation')
    mock_cf_instance = mock_cf.return_value
    mock_cf_instance.check_stack_exists.return_value = False
    mock_cf_instance.deploy_stack.return_value = True
    mock_cf_instance.check_stack_status.return_value = True
    mock_cf_instance.get_cfn_outputs.return_value = {
        'RoleName': 'test-role',
        'AccTableName': 'test-acc-table',
        'RecTableName': 'test-rec-table',
        'Region': 'us-east-1'
    }
    mock_cf_instance.main_account_id = '123456789012'
    
    # Mock cache operations
    mock_cache = mocker.patch('utils.cache_manager.CLOUDFORMATION_CACHE')
    mock_cache.get.return_value = 'test-acc-table'  # Return table name when requested
    
    # Mock database operations
    mock_db = mocker.patch('db.crud.DatabaseManager')
    mock_db_instance = mock_db.return_value
    
    # Mock role validation
    mock_clients = mocker.patch('aws.wrappers.clients.AWSClients')
    mock_clients.validate_manual_deployment_role_assumptions.return_value = [
        ('123456789012', True),
        ('987654321098', True)
    ]
    
    # Simulate user inputs: manual mode (no), workspace, and confirmation
    simulated_input = "no\ntest\nyes\n"
    
    # Create CliRunner instance
    runner = CliRunner()
    
    # Execute the command
    result = runner.invoke(
        cli_app,
        ["deploy"],
        input=simulated_input,
        prog_name="bluearch"
    )
    
    # Assertions
    assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
    assert "Deploy completed" in result.stdout
    mock_cf_instance.deploy_stack.assert_called_once_with(
        workspace="test",
        auto_mode="no"
    )
    mock_cf_instance.check_stack_status.assert_called_once()
    mock_db_instance.populate_accounts_and_regions.assert_called_once()
    mock_manual_instructions.assert_called_once()  # Verify the instructions were displayed

def test_feature_request_submission(mocker, mock_auth_wrapper):
    """Test feature request submission"""
    # Configure auth wrapper
    mock_auth_wrapper.get_api_key.return_value = "BLUE-12345678-1234-1234-1234-123456789012"
    mock_auth_wrapper.is_subscribed_to_marketplace.return_value = (False, False)

    # Mock the send_feature_request function in the correct namespace
    mock_send = mocker.patch('aws.misc.feature_requests.send_feature_request')
    mock_send.return_value = (True, "Feature request submitted successfully")

    # Simulate user input for the feature request message
    result = runner.invoke(
        cli_app,
        ["feature-request"],
        input="Test feature request\n",
        prog_name="bluearch"
    )

    # Assertions
    assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
    assert "Feature request submitted successfully" in result.stdout

    # Ensure send_feature_request was called once with correct arguments
    mock_send.assert_called_once_with("BLUE-12345678-1234-1234-1234-123456789012", "Test feature request")

# def test_feature_request_no_api_key(mocker, mock_auth_wrapper):
#     """Test feature request submission without API key"""

#     # Mock auth wrapper to return no API key
#     mock_auth_wrapper.get_api_key.return_value = None
#     mock_auth_wrapper.is_subscribed_to_marketplace.return_value = (False, False)


#     # Simulate user input for the feature request message
#     result = runner.invoke(
#         cli_app,
#         ["feature-request"],
#         input="Test feature request\n",
#         prog_name="bluearch"
#     )

#     # Assertions
#     assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
#     assert "API key not found" in result.stdout

# def test_update_with_changes(mocker):
#     """Test update command when changes are present"""
#     # Mock the CloudFormation wrapper
#     mock_cf = mocker.patch('aws.wrappers.cloudformation.CloudFormation')
#     mock_cf_instance = mock_cf.return_value
#     mock_cf_instance.check_stack_exists.return_value = True
#     mock_cf_instance.create_change_set.return_value = True
#     mock_cf_instance.wait_for_change_set.return_value = "UPDATE_COMPLETE"

#     # Simulate user confirmations for update
#     simulated_input = "yes\nyes\n"

#     result = runner.invoke(
#         cli_app,
#         ["update"],
#         input=simulated_input,
#         prog_name="bluearch"
#     )

#     # Assertions
#     assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
#     assert "BlueArch CLI + CloudFormation stack were updated successfully." in result.stdout
#     mock_cf_instance.create_change_set.assert_called_once()
#     mock_cf_instance.execute_change_set.assert_called_once()
#     mock_cf_instance.wait_for_change_set.assert_called_once()

# def test_update_no_changes(mocker, mock_config_manager):
#     """Test update command when no changes are detected"""
#     # Mock system checks
#     mocker.patch('os.geteuid', return_value=0)
#     mocker.patch('platform.machine', return_value='x86_64')
#     mocker.patch('zipfile.ZipFile')  # Mock zipfile operations

#     # Mock subprocess calls
#     mock_subprocess = mocker.patch('subprocess.run')
#     mock_subprocess.return_value.returncode = 0

#     # Mock the CloudFormation wrapper
#     mock_cf = mocker.patch('aws.wrappers.cloudformation.CloudFormation')
#     mock_cf_instance = mock_cf.return_value
#     mock_cf_instance.check_stack_exists.return_value = True
#     mock_cf_instance.create_change_set.return_value = False
#     mock_cf_instance.describe_change_set.return_value = None  # Mocking to simulate no changes

#     # Simulate user confirmation
#     simulated_input = "yes\n"

#     result = runner.invoke(
#         cli_app,
#         ["update"],
#         input=simulated_input,
#         prog_name="bluearch"
#     )

#     # Assertions
#     assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
#     assert "Bluearch Cloudformation Stack not updated: No changes has been detected." in result.stdout
#     mock_cf_instance.create_change_set.assert_called_once()
#     mock_cf_instance.delete_change_set.assert_called_once()


def test_update_cli_download_failure(mocker, mock_cloudformation, mock_error_handler):
    """Test update command when download fails"""
    # Mock platform checks
    mocker.patch('platform.machine', return_value='x86_64')
    mocker.patch('sys.platform', return_value='linux')
    
    # Mock requests to simulate download failure
    mock_response = mocker.Mock()
    mock_response.raise_for_status.side_effect = requests.exceptions.RequestException("Download failed")
    mock_requests = mocker.patch('requests.get', return_value=mock_response)

    # Mock filesystem operations
    mock_makedirs = mocker.patch('os.makedirs')
    mocker.patch('os.chmod')
    mocker.patch('os.rename')
    mocker.patch('tempfile.mkdtemp', return_value='/tmp/test')
    mocker.patch('shutil.rmtree')
    
    # Mock Path.home()
    mock_home = mocker.patch('pathlib.Path.home')
    mock_home.return_value = pathlib.Path("/home/user")
    
    # Mock execution module functions
    mocker.patch('commons.execution.confirm_update', return_value=True)
    
    # Mock CloudFormation operations
    mock_cloudformation.return_value.check_stack_exists.return_value = False
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\n",
        prog_name="bluearch"
    )

    # Verify error message
    assert "Error downloading update" in result.stdout
    
    # Verify requests was called with correct URL
    mock_requests.assert_called_once()
    url = mock_requests.call_args[0][0]
    assert "linux_x86_64" in url, f"Expected Linux x86_64 URL, got: {url}"
    
    # Verify filesystem operations
    mock_makedirs.assert_called_once()
    
    # Verify CloudFormation was not called further since binary update failed
    assert not mock_cloudformation.return_value.create_change_set.called

def test_feature_request_marketplace_subscription(mocker, mock_auth_wrapper, mock_error_handler):
    """Test feature request with marketplace subscription"""
    # Setup
    mock_auth_wrapper.is_subscribed_to_marketplace.return_value = (True, "prod-1")
    mock_send = mocker.patch('aws.misc.feature_requests.send_feature_request')
    mock_send.return_value = (True, "Feature request submitted successfully")

    # Execute with simulated input
    result = runner.invoke(
        cli_app,
        ["feature-request"],
        input="Test feature request\n",  # Provide input for the prompt
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "Feature request submitted successfully" in result.stdout
    mock_send.assert_called_once_with("prod-1", "Test feature request")

def test_feature_request_with_api_key(mocker, mock_auth_wrapper, mock_error_handler):
    """Test feature request with API key"""
    # Setup
    mock_auth_wrapper.is_subscribed_to_marketplace.return_value = (False, None)
    mock_auth_wrapper.get_api_key.return_value = "test-api-key"
    mock_send = mocker.patch('aws.misc.feature_requests.send_feature_request')
    mock_send.return_value = (True, "Feature request submitted successfully")

    # Execute
    result = runner.invoke(
        cli_app,
        ["feature-request"],
        input="Test feature request\n",
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "Feature request submitted successfully" in result.stdout
    mock_auth_wrapper.get_api_key.assert_called_once()

def test_feature_request_no_api_key(mock_auth_wrapper, mock_error_handler):
    """Test feature request without API key"""
    # Setup
    mock_auth_wrapper.is_subscribed_to_marketplace.return_value = (False, None)
    mock_auth_wrapper.get_api_key.return_value = None

    # Execute
    result = runner.invoke(
        cli_app,
        ["feature-request"],
        input="Test feature request\n",
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "API key not found" in result.stdout

def test_delete_stack_exists_confirmed(mock_cloudformation, mock_error_handler, mock_prompt):
    # Setup
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    mock_prompt.ask.return_value = "yes"
    mock_cloudformation.return_value.delete_stack.return_value = True
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["delete"],
        prog_name="bluearch"
    )
    
    # Verify
    mock_cloudformation.return_value.delete_stack.assert_called_once()

def test_delete_stack_exists_aborted(mock_cloudformation, mock_error_handler, mock_prompt):
    """Test delete stack when user aborts"""
    # Setup
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    mock_prompt.ask.return_value = "no"

    # Execute with simulated input
    result = runner.invoke(
        cli_app,
        ["delete"],
        input="no\n",  # Simulate user entering "no"
        prog_name="bluearch",
        catch_exceptions=False
    )

    # Verify
    assert result.exit_code == 0
    mock_cloudformation.return_value.delete_stack.assert_not_called()
    assert "Stack deletion aborted." in result.stdout

def test_delete_stack_not_exists(mock_cloudformation, mock_error_handler, mock_console):
    # Setup
    mock_cloudformation.return_value.check_stack_exists.return_value = False
    
    result = runner.invoke(
        cli_app,
        ["delete"],
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    mock_console.return_value.print.assert_called_with("[yellow]The CloudFormation stack does not exist. No action needed.[/yellow]")

# def test_show_accounts_regions_exists(mocker, mock_get_accounts_and_regions, mock_display):
#     """Test show accounts and regions command"""
#     # Setup
#     mock_get_accounts_and_regions.return_value = {
#         "123": {"account_name": "test", "regions": ["us-east-1"]}
#     }

#     # Execute
#     result = runner.invoke(
#         cli_app,
#         ["show-accounts-and-regions"],
#         prog_name="bluearch"
#     )

#     # Verify
#     assert result.exit_code == 0
#     mock_display.display_accounts_and_regions.assert_called_once_with(
#         mock_get_accounts_and_regions.return_value
#     )

def test_show_accounts_regions_not_exists_persist(mock_get_accounts_and_regions, mock_prompt, mocker):
    # Setup
    mock_get_accounts_and_regions.side_effect = [None, {"123": {"account_name": "test", "regions": ["us-east-1"]}}]
    mock_prompt.ask.return_value = "yes"
    mock_refresh = mocker.patch('commons.get.refresh_accounts_n_regions_table')
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["show-accounts-and-regions"],
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    mock_refresh.assert_called_once()

def test_update_with_changes(mocker, mock_cloudformation, mock_error_handler):
    """Test update command with changes"""
    # Mock os.geteuid to return 0 (root user)
    mocker.patch('os.geteuid', return_value=0)
    
    # Mock subprocess calls for CLI update
    mock_subprocess = mocker.patch('subprocess.run')
    mock_subprocess.return_value.returncode = 0
    
    # Mock platform.machine()
    mocker.patch('platform.machine', return_value='x86_64')
    
    # Setup CloudFormation mocks
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    mock_cloudformation.return_value.create_change_set.return_value = True
    mock_cloudformation.return_value.describe_change_set.return_value = {
        "Changes": [{"ResourceChange": {"Action": "Add"}}]
    }
    mock_cloudformation.return_value.wait_for_change_set.return_value = "UPDATE_COMPLETE"

    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\nyes\n",  # Confirm update and changes
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "BlueArch CLI + CloudFormation stack were updated" in result.stdout
    mock_cloudformation.return_value.execute_change_set.assert_called_once()

def test_update_no_changes(mocker, mock_cloudformation, mock_error_handler):
    """Test update command with no changes"""
    # Setup
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    mock_cloudformation.return_value.create_change_set.return_value = False
    mock_cloudformation.return_value.describe_change_set.return_value = None

    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\n",
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "Bluearch Cloudformation Stack not updated: No changes has been detected." in result.stdout

# def test_update_without_sudo(mocker, mock_cloudformation, mock_error_handler):
#     """Test update command without sudo privileges"""
#     # Mock os.geteuid to return non-zero (non-root user)
#     mocker.patch('os.geteuid', return_value=1000)
    
#     # Mock the confirmation prompts
#     mock_confirm = mocker.patch('commons.execution.confirm_update', return_value=True)
#     mock_confirm_changes = mocker.patch('commons.execution.confirm_update_with_changes', return_value=True)
    
#     # Mock version controller
#     mock_prompt = mocker.patch('aws.misc.version_controller.ask_for_enable_auto_update')
    
#     # Mock CloudFormation wait_for_change_set to return None (success)
#     mock_cloudformation.wait_for_change_set.return_value = None
    
#     # Execute
#     result = runner.invoke(
#         cli_app,
#         ["update"],
#         input="yes\n",  # For any remaining prompts
#         prog_name="bluearch"
#     )

#     # Strip ANSI color codes and normalize newlines
#     cleaned_output = result.stdout.replace("\x1b[31m", "").replace("\x1b[0m", "").replace("\x1b[33m", "")
    
#     # Verify the error is handled and message is displayed
#     assert result.exit_code == 0  # Error handler catches the exception, so exit code is 0
#     expected_msg = "CLI update failed: Please run this command with sudo -E: 'sudo -E bluearch update'"
#     assert expected_msg in cleaned_output.replace(".", "")  # Remove period for comparison
    
#     # Verify error handler was called with PermissionError
#     mock_error_handler.handle_error.assert_called_once()
#     args, _ = mock_error_handler.handle_error.call_args
#     assert isinstance(args[0], PermissionError)
    
#     # Verify CloudFormation was not called since we failed at sudo check
#     mock_cloudformation.wait_for_change_set.assert_not_called()

def test_update_with_unsupported_architecture(mocker, mock_error_handler):
    """Test update command with unsupported architecture"""
    # Mock platform.machine to return unsupported architecture
    mocker.patch('platform.machine', return_value='powerpc')
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\n",
        prog_name="bluearch"
    )

    # Verify
    assert "Unsupported architecture: powerpc" in result.stdout

def test_update_download_error(mocker, mock_cloudformation, mock_error_handler):
    """Test update command with download error"""
    # Mock platform checks
    mocker.patch('platform.machine', return_value='x86_64')
    mocker.patch('sys.platform', return_value='linux')
    
    # Mock requests to simulate download error
    mock_response = mocker.Mock()
    mock_response.raise_for_status.side_effect = requests.exceptions.RequestException("Failed to download update")
    mocker.patch('requests.get', return_value=mock_response)
    
    # Mock filesystem operations
    mocker.patch('os.makedirs')
    mocker.patch('tempfile.mkdtemp', return_value='/tmp/test')
    mocker.patch('shutil.rmtree')
    
    # Mock error handler
    mock_error_handler.handle_update_error.side_effect = lambda e, cf: None
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\n",
        prog_name="bluearch"
    )

    # Verify
    assert "Error downloading update" in result.stdout
    mock_error_handler.handle_update_error.assert_called_once()
    # CloudFormation should not be called because binary update failed
    assert not mock_cloudformation.check_stack_exists.called

def test_update_successful(mocker, mock_cloudformation, mock_error_handler):
    """Test successful update process"""
    # Mock platform checks
    mocker.patch('platform.machine', return_value='x86_64')
    mocker.patch('sys.platform', return_value='linux')
    
    # Mock successful requests response
    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers = {'content-length': '1024'}
    mock_response.iter_content.return_value = [b'binary_content']
    mocker.patch('requests.get', return_value=mock_response)

    # Mock filesystem operations
    mock_makedirs = mocker.patch('os.makedirs')
    mock_chmod = mocker.patch('os.chmod')
    mock_rename = mocker.patch('os.rename')
    mock_tempdir = mocker.patch('tempfile.mkdtemp', return_value='/tmp/test')
    mocker.patch('shutil.rmtree')
    
    # Mock file operations
    mock_open = mocker.patch('builtins.open', mocker.mock_open())
    mocker.patch('os.path.exists', return_value=False)
    
    # Mock CloudFormation operations
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    mock_cloudformation.return_value.create_change_set.return_value = None
    mock_cloudformation.return_value.describe_change_set.return_value = {
        'Changes': [
            {
                'ResourceChange': {
                    'Action': 'Modify',
                    'LogicalResourceId': 'TestResource',
                    'PhysicalResourceId': 'test-id',
                    'ResourceType': 'AWS::IAM::Role',
                    'Replacement': 'False'
                }
            }
        ]
    }
    
    # Mock execution module functions
    mocker.patch('commons.execution.confirm_update', return_value=True)
    mocker.patch('commons.execution.confirm_update_with_changes', return_value=True)
    mocker.patch('commons.execution.handle_no_updates', return_value=None)
    mocker.patch('commons.execution.handle_update_aborted', return_value=None)
    mocker.patch('commons.execution.execute_update', return_value=None)
    
    # Mock cache operations
    mock_delete_cache = mocker.patch('utils.cache.delete_cache')
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\nyes\n",  # One yes for binary update, one for CloudFormation update
        prog_name="bluearch"
    )

    # Verify binary update
    assert mock_makedirs.called
    assert mock_chmod.called
    assert mock_rename.called
    assert mock_open.called
    assert "BlueArch CLI has been successfully updated" in result.stdout
    assert mock_delete_cache.called
    
    # Verify CloudFormation operations
    assert mock_cloudformation.return_value.check_stack_exists.called
    assert mock_cloudformation.return_value.create_change_set.called
    assert mock_cloudformation.return_value.describe_change_set.called

def test_update_with_backup_recovery(mocker, mock_cloudformation, mock_error_handler):
    """Test update process with backup recovery on failure"""
    # Mock platform checks
    mocker.patch('platform.machine', return_value='x86_64')
    mocker.patch('sys.platform', return_value='linux')
    
    # Mock requests to fail after download
    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers = {'content-length': '1024'}
    mock_response.iter_content.return_value = [b'binary_content']
    mocker.patch('requests.get', return_value=mock_response)

    # Mock filesystem operations
    mocker.patch('os.makedirs')
    mocker.patch('os.chmod')
    
    # Mock paths
    install_dir = "/home/user/.local/bin"
    temp_dir = "/tmp/test"
    binary_path = f"{install_dir}/bluearch"
    backup_path = f"{install_dir}/bluearch.bak"
    temp_path = f"{temp_dir}/bluearch.tmp"
    
    # Mock Path.home()
    mock_home = mocker.patch('pathlib.Path.home')
    mock_home.return_value = pathlib.Path("/home/user")
    
    # Mock file existence checks
    mock_exists = mocker.patch('os.path.exists')
    mock_exists.side_effect = lambda p: p in [binary_path, backup_path]
    
    # Mock os.remove for backup cleanup
    mock_remove = mocker.patch('os.remove')
    
    # Mock rename operations
    mock_rename = mocker.patch('os.rename')
    def rename_side_effect(src, dst):
        if temp_path in str(src):
            raise OSError("Permission denied")
    mock_rename.side_effect = rename_side_effect
    
    # Mock tempfile and cleanup
    mocker.patch('tempfile.mkdtemp', return_value=temp_dir)
    mocker.patch('shutil.rmtree')
    
    # Mock open for file operations
    mock_open = mocker.patch('builtins.open', mocker.mock_open())
    
    # Mock execution module functions
    mocker.patch('commons.execution.confirm_update', return_value=True)
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\n",
        prog_name="bluearch"
    )

    # Verify error message
    assert "Error during update" in result.stdout
    
    # Verify rename operations
    rename_calls = mock_rename.call_args_list
    assert len(rename_calls) >= 2  # At least backup creation and restore
    
    # Verify backup was created
    backup_call = rename_calls[0]
    assert str(binary_path) in str(backup_call[0][0])  # Source is original binary
    assert str(backup_path) in str(backup_call[0][1])  # Destination is backup
    
    # Verify backup was restored after failure
    restore_call = rename_calls[-1]
    assert str(backup_path) in str(restore_call[0][0])  # Source is backup
    assert str(binary_path) in str(restore_call[0][1])  # Destination is original binary

def test_update_macos_path(mocker, mock_cloudformation, mock_error_handler):
    """Test update process on macOS with correct path"""
    # Mock platform checks - ensure this happens before any imports
    platform_mock = mocker.patch('sys.platform', new='darwin')
    mocker.patch('platform.machine', return_value='arm64')
    
    # Import after mocking
    from commons.execution import get_install_dir
    
    # Mock successful requests response
    mock_response = mocker.Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers = {'content-length': '1024'}
    mock_response.iter_content.return_value = [b'binary_content']
    mocker.patch('requests.get', return_value=mock_response)

    # Mock Path.home()
    mock_home = mocker.patch('pathlib.Path.home')
    mock_home.return_value = pathlib.Path("/Users/testuser")
    
    # Expected paths based on mocked platform and home
    install_dir = get_install_dir()  # This should now return the macOS path
    temp_dir = "/tmp/test"
    binary_path = f"{install_dir}/bluearch"
    backup_path = f"{install_dir}/bluearch.bak"
    temp_path = f"{temp_dir}/bluearch.tmp"

    # Mock filesystem operations
    mock_makedirs = mocker.patch('os.makedirs')
    mocker.patch('os.chmod')
    mocker.patch('os.rename')
    mocker.patch('tempfile.mkdtemp', return_value=temp_dir)
    mocker.patch('shutil.rmtree')
    
    # Mock file operations
    mock_open = mocker.patch('builtins.open', mocker.mock_open())
    mocker.patch('os.path.exists', return_value=False)
    
    # Mock execution module functions
    mocker.patch('commons.execution.confirm_update', return_value=True)
    mocker.patch('commons.execution.confirm_update_with_changes', return_value=True)
    
    # Mock CloudFormation operations
    mock_cloudformation.return_value.check_stack_exists.return_value = False
    
    # Execute
    result = runner.invoke(
        cli_app,
        ["update"],
        input="yes\n",
        prog_name="bluearch"
    )

    # Verify success message
    assert "BlueArch CLI has been successfully updated" in result.stdout
    
    # Verify macOS-specific path was created
    expected_path = str(pathlib.Path("/Users/testuser/Library/Application Support/bluearch/bin"))
    actual_calls = [call[0][0] for call in mock_makedirs.call_args_list]
    assert expected_path in actual_calls, f"Expected path {expected_path} not found in makedirs calls: {actual_calls}"
    
    # Verify platform check was used correctly
    assert platform_mock == 'darwin', "Platform mock was not properly set"
    
    # Verify correct installation directory was used
    assert "Library/Application Support/bluearch/bin" in install_dir, f"Unexpected install directory: {install_dir}"

def test_deploy_add_accounts_success(
    mocker, 
    runner, 
    mock_cloudformation, 
    mock_deploy_mode,
    mock_display,
    mock_db_manager
):
    """Test successful addition of accounts to existing manual deployment"""
    # Mock stack exists
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    
    # Mock CloudFormation outputs
    mock_cloudformation.return_value.get_cfn_outputs.return_value = {
        'RoleName': 'test-role',
        'AccTableName': 'test-acc-table',
        'RecTableName': 'test-rec-table',
        'Region': 'us-east-1'
    }
    
    # Mock display_manual_instructions_workflow to return some account IDs
    new_accounts = ['123456789012', '210987654321']
    mock_display.display_manual_instructions_workflow.return_value = new_accounts
    
    # Mock role validation to succeed
    mock_validate = mocker.patch('aws.wrappers.clients.AWSClients.validate_manual_deployment_role_assumptions')
    mock_validate.return_value = [
        ('123456789012', True),
        ('210987654321', True)
    ]

    # Mock DatabaseManager directly in the module where it's used
    mock_db = mocker.patch('db.crud.DatabaseManager')
    db_instance = mock_db.return_value
    db_instance._account_ids = None

    # Execute command with simulated input
    result = runner.invoke(
        cli_app,
        ["deploy", "--add-accounts"],
        input="123456789012\n210987654321\ndone\nyes\n",  # Simulate user input
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "Successfully added new accounts to BlueArch" in result.stdout
    mock_cloudformation.return_value.check_stack_exists.assert_called_once()
    
    # Verify DatabaseManager was used correctly
    mock_db.assert_called_once()
    db_instance = mock_db.return_value
    assert hasattr(db_instance, '_account_ids')
    db_instance.populate_accounts_and_regions.assert_called_once()

def test_deploy_add_accounts_no_stack(
    mocker, 
    runner, 
    mock_cloudformation, 
    mock_deploy_mode
):
    """Test add-accounts when no stack exists"""
    # Mock stack doesn't exist
    mock_cloudformation.return_value.check_stack_exists.return_value = False

    # Execute command
    result = runner.invoke(
        cli_app,
        ["deploy", "--add-accounts"],
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "No existing BlueArch deployment found" in result.stdout
    mock_cloudformation.return_value.check_stack_exists.assert_called_once()

def test_deploy_add_accounts_wrong_mode(
    mocker, 
    runner, 
    mock_cloudformation
):
    """Test add-accounts in auto deployment mode"""
    # Mock stack exists
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    
    # Mock auto deployment mode
    mocker.patch('commons.globals.DEPLOY_MODE', 'auto')

    # Execute command
    result = runner.invoke(
        cli_app,
        ["deploy", "--add-accounts"],
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "Adding accounts is only supported for manual deployments" in result.stdout

def test_deploy_add_accounts_validation_fail(
    mocker, 
    runner, 
    mock_cloudformation, 
    mock_deploy_mode,
    mock_display
):
    """Test add-accounts when role validation fails"""
    # Mock stack exists
    mock_cloudformation.return_value.check_stack_exists.return_value = True
    
    # Mock manual workflow to return accounts
    mock_display.display_manual_instructions_workflow.return_value = ['123456789012']
    
    # Mock role validation to fail
    mock_validate = mocker.patch('aws.wrappers.clients.AWSClients.validate_manual_deployment_role_assumptions')
    mock_validate.return_value = [('123456789012', False)]

    # Execute command with simulated input
    result = runner.invoke(
        cli_app,
        ["deploy", "--add-accounts"],
        input="123456789012\ndone\n",  # Simulate user input
        prog_name="bluearch"
    )

    # Verify
    assert result.exit_code == 0
    assert "No valid accounts found to add" in result.stdout
