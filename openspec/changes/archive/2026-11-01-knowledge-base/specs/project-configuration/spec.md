# Spec Delta

## MODIFIED Requirements

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
