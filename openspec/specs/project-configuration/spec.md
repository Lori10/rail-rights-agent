# project-configuration Specification

## Purpose

Gives the application and the infrastructure code one validated source for model ids and the AWS environment, so models can be swapped without code changes and nothing can target a region other than eu-north-1.

## Requirements

### Requirement: Defaults match the project's AWS environment
When no overrides are set, the configuration SHALL provide these defaults:
- primary model `eu.anthropic.claude-haiku-4-5-20251001-v1:0`
- comparison model `eu.amazon.nova-2-lite-v1:0`
- embedding model `amazon.titan-embed-text-v2:0`
- region `eu-north-1`
- AWS profile `railagent`

#### Scenario: Load with no overrides
- **WHEN** the configuration is loaded with none of its environment variables set
- **THEN** it returns the five default values above

### Requirement: Model ids and AWS profile are overridable by environment variables
Each of these values SHALL be overridable by its own documented environment variable, without code changes:
- primary model id
- comparison model id
- embedding model id
- AWS profile

#### Scenario: Override the primary model
- **WHEN** the primary-model environment variable is set to `eu.amazon.nova-2-lite-v1:0`
- **THEN** the loaded configuration's primary model id is `eu.amazon.nova-2-lite-v1:0`
- **AND** every other value keeps its default

#### Scenario: Override the AWS profile
- **WHEN** the AWS-profile environment variable is set to `other-profile`
- **THEN** the loaded configuration's AWS profile is `other-profile`

### Requirement: Empty values are rejected
Loading the configuration SHALL fail, with an error naming the variable, when any configured value is empty or only whitespace.

#### Scenario: Empty model id
- **WHEN** the embedding-model environment variable is set to an empty string
- **THEN** loading the configuration fails
- **AND** the error message names the embedding-model variable

### Requirement: Region is locked to eu-north-1
The configuration SHALL accept only `eu-north-1` as the AWS region. Any other value from the environment SHALL make loading fail with an error that names the allowed region.

#### Scenario: Region set to eu-north-1
- **WHEN** the region environment variable is set to `eu-north-1`
- **THEN** loading succeeds and the region is `eu-north-1`

#### Scenario: Region set elsewhere
- **WHEN** the region environment variable is set to `us-east-1`
- **THEN** loading the configuration fails
- **AND** the error message names `eu-north-1` as the only allowed region

### Requirement: Configuration is read-only after loading
A loaded configuration SHALL NOT be modifiable at runtime.

#### Scenario: Attempt to change a loaded value
- **WHEN** code tries to assign a new primary model id to a loaded configuration
- **THEN** the assignment raises an error and the value is unchanged

### Requirement: Model ids are not hardcoded outside the configuration
Bedrock model and inference-profile ids SHALL appear only in the configuration module and its tests, never elsewhere in application or infrastructure source.

#### Scenario: Scan source for model ids
- **WHEN** the application and infrastructure source is scanned for Bedrock model-id patterns (`anthropic.`, `amazon.nova`, `cohere.embed`, `amazon.titan-embed`)
- **THEN** matches appear only in the configuration module
