"""Names shared by the tools stack (infra), the handlers and the seed command."""

STACK_NAME = "RailRightsAgent-Tools"

OUTPUT_TRIPS_TABLE = "TripsTableName"
OUTPUT_CLAIMS_TABLE = "ClaimsTableName"
OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN = "GetTrainDelayFunctionArn"
OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN = "CalculateCompensationFunctionArn"
OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN = "SubmitClaimFunctionArn"

# Table names reach the functions through these environment variables.
ENV_TRIPS_TABLE = "TRIPS_TABLE"
ENV_CLAIMS_TABLE = "CLAIMS_TABLE"

HANDLER_MODULE = "rail_rights_agent.tools.handlers"
TOOL_NAMES = ("get_train_delay", "calculate_compensation", "submit_claim")
