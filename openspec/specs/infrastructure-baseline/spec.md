# infrastructure-baseline Specification

## Purpose

Defines the contract every infrastructure stack follows: where it deploys, how it is tagged for cost tracking, how the whole system is deployed and destroyed in one command, and the cost alert that protects the account's credit.

## Requirements

### Requirement: Stacks target the configured account and eu-north-1
Every stack in the infrastructure app SHALL synthesise for region `eu-north-1`. The account SHALL come from the deploying credentials, not from source code.

#### Scenario: Synthesise the app
- **WHEN** the infrastructure app is synthesised
- **THEN** every stack's environment region is `eu-north-1`

### Requirement: Every taggable resource carries the project tags
Every taggable resource in every stack SHALL carry these tags:
- `project` = `rail-rights-agent`
- `environment` = `dev`
- `managed-by` = `cdk`
- `repo` = `Lori10/rail-rights-agent`

#### Scenario: Resource added to a stack
- **WHEN** a taggable resource is added to any stack of the app and the app is synthesised
- **THEN** the synthesised resource carries all four tags with those values

### Requirement: Synthesis works offline
The infrastructure app SHALL synthesise without AWS credentials or network access to AWS, so it can be tested in the default offline test run and in CI.

#### Scenario: Synthesise without credentials
- **WHEN** the app is synthesised in an environment with no AWS credentials
- **THEN** synthesis succeeds and produces a template for every stack

### Requirement: One command deploys and one command destroys
The repository SHALL provide a single command that deploys every stack, and a single command that destroys every stack. Both SHALL use the configured AWS profile and region.

#### Scenario: Deploy
- **WHEN** the deploy command is run with valid credentials for the configured profile
- **THEN** every stack of the app is deployed to eu-north-1

#### Scenario: Destroy
- **WHEN** the destroy command is run after a deploy
- **THEN** every stack of the app is deleted and no stack of the app remains in the account

### Requirement: Cost-alert budget when an alert email is configured
When an alert email is set in the environment, the app SHALL include a monthly cost budget with these email notifications:
- actual spend reaches 50% of the limit
- actual spend reaches 80% of the limit
- forecast spend reaches 100% of the limit

Without an alert email, the app SHALL contain no budget. The email address SHALL NOT be stored in the repository.

#### Scenario: Alert email set
- **WHEN** the app is synthesised with an alert email configured
- **THEN** it contains one monthly cost budget with the three notifications, each sent to that address

#### Scenario: Alert email not set
- **WHEN** the app is synthesised without an alert email
- **THEN** it contains no budget resource
