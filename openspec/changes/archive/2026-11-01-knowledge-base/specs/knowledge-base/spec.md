# Spec Delta

## Purpose

Holds the passenger-rights source documents (EU Regulation 2021/782 in English and German, DB conditions of carriage in German) as a searchable knowledge base, and returns ranked passages with enough source attribution for the agent to cite them.

## ADDED Requirements

### Requirement: The knowledge base holds exactly the catalogued source documents
The knowledge base SHALL be built from exactly these documents, each tagged with a document id and a language:
- `eu-2021-782-en.pdf`: document `eu-2021-782`, language `en`
- `eu-2021-782-de.pdf`: document `eu-2021-782`, language `de`
- `db-befoerderungsbedingungen-de.pdf`: document `db-befoerderungsbedingungen`, language `de`

#### Scenario: Ingest the catalogue
- **WHEN** ingestion runs with all three files present in the local source folder
- **THEN** exactly these three documents are uploaded, each with its document id and language attached as metadata

#### Scenario: A catalogued file is missing
- **WHEN** ingestion runs and one of the three files is absent from the local source folder
- **THEN** ingestion fails with an error naming the missing file
- **AND** nothing is uploaded and no ingestion job is started

### Requirement: Ingestion waits for the job and reports its outcome
After uploading, ingestion SHALL start a knowledge-base ingestion job and wait until the job finishes. It SHALL then report the scanned, indexed and failed document counts. It succeeds only if the job completes with zero failed documents; otherwise it exits non-zero and gives the reason.

#### Scenario: Job completes cleanly
- **WHEN** the ingestion job finishes with status complete and zero failed documents
- **THEN** ingestion exits with status 0 and reports the scanned, indexed and failed counts

#### Scenario: Job fails
- **WHEN** the ingestion job finishes with status failed
- **THEN** ingestion exits with a non-zero status and reports the failure reasons returned by the service

#### Scenario: Some documents fail
- **WHEN** the ingestion job completes but reports one or more failed documents
- **THEN** ingestion exits with a non-zero status and reports the failed count

### Requirement: Ingestion finds its targets from the deployed stack
Ingestion SHALL read the knowledge base id, data source id and documents bucket from the deployed knowledge-base stack's outputs in the configured region. It SHALL NOT need these ids set by hand.

#### Scenario: Stack is deployed
- **WHEN** ingestion runs against a deployed knowledge-base stack
- **THEN** it uploads to that stack's documents bucket and starts the job on that stack's knowledge base and data source

#### Scenario: Stack is not deployed
- **WHEN** ingestion runs and the knowledge-base stack does not exist
- **THEN** ingestion fails with an error saying the stack must be deployed first

### Requirement: Retrieval returns attributed passages
Retrieval SHALL return passages ranked by relevance, best first. Each passage SHALL carry:
- its text
- its document id
- its language
- its source URI
- its relevance score
- its page number, when the service provides one

#### Scenario: Question about delay compensation
- **WHEN** retrieval is asked a question and the knowledge base returns matching chunks
- **THEN** each returned passage has non-empty text, a catalogued document id, a language of `en` or `de`, a source URI and a score
- **AND** the passages are in the order the service ranked them

#### Scenario: No matches
- **WHEN** the knowledge base returns no chunks for a question
- **THEN** retrieval returns an empty list rather than failing

### Requirement: Retrieval can be restricted to one language
Retrieval SHALL accept an optional language (`en` or `de`). When one is given, every returned passage SHALL be in that language.

#### Scenario: German only
- **WHEN** retrieval is asked a question with language `de`
- **THEN** the request to the knowledge base filters on language `de`
- **AND** every returned passage has language `de`

#### Scenario: Unsupported language
- **WHEN** retrieval is asked a question with language `fr`
- **THEN** retrieval fails with an error naming the supported languages, without calling AWS

### Requirement: Retrieval rejects invalid requests before calling AWS
Retrieval SHALL reject the following before making any AWS call:
- an empty or whitespace-only question
- a result count outside 1–20

When no count is given, it SHALL return up to 5 passages.

#### Scenario: Empty question
- **WHEN** retrieval is asked an empty question
- **THEN** it fails with an error saying the question is empty, without calling AWS

#### Scenario: Result count out of range
- **WHEN** retrieval is asked for 0 or 21 results
- **THEN** it fails with an error naming the allowed range, without calling AWS

#### Scenario: Default result count
- **WHEN** retrieval is asked a question without a result count
- **THEN** it requests 5 results from the knowledge base

### Requirement: Service errors surface as knowledge-base errors
When the knowledge base service rejects a retrieval or ingestion call, the system SHALL raise one project-specific knowledge-base error that keeps the service's error code and message. It SHALL NOT expose the SDK's exception type to callers.

#### Scenario: Unknown knowledge base
- **WHEN** retrieval targets a knowledge base id that the service reports as not found
- **THEN** retrieval raises the knowledge-base error, and its message includes the service's error code

### Requirement: Knowledge-base infrastructure is private, least-privilege and pay-per-use
The knowledge-base stack SHALL:
- block all public access to the documents bucket, encrypt it and require TLS
- store vectors in S3 Vectors, never in OpenSearch Serverless
- limit its service role to invoking only the configured embedding model, reading only the documents bucket, and reading and writing only its own vector index

#### Scenario: Synthesise the stack
- **WHEN** the infrastructure app is synthesised
- **THEN** the knowledge-base stack contains a documents bucket with public access blocked, encryption and a TLS-only bucket policy, an S3 Vectors bucket and index, a knowledge base using S3 Vectors storage, and an S3 data source
- **AND** no stack contains an OpenSearch Serverless resource

#### Scenario: Service role scope
- **WHEN** the knowledge-base stack is synthesised
- **THEN** the service role can be assumed only by Bedrock for this account
- **AND** its model permission names only the configured embedding model, its S3 permissions name only the documents bucket, and its S3 Vectors permissions name only the knowledge base's index

### Requirement: The vector index matches the embedding model
The vector index SHALL use float32 vectors, the dimension of the configured embedding model (1024), and cosine distance. It SHALL store chunk text and Bedrock's own chunk metadata as non-filterable metadata, so that only small attributes (document id, language) count against the filterable-metadata limit.

#### Scenario: Index configuration
- **WHEN** the knowledge-base stack is synthesised
- **THEN** the index has data type float32, dimension 1024 and distance metric cosine
- **AND** its non-filterable metadata keys include the knowledge base's chunk-text and chunk-metadata keys
- **AND** the knowledge base's embedding configuration declares 1024 float32 dimensions

### Requirement: Knowledge-base stack exposes its ids
The knowledge-base stack SHALL output the knowledge base id, the data source id and the documents bucket name.

#### Scenario: Stack outputs
- **WHEN** the knowledge-base stack is synthesised
- **THEN** it declares outputs for the knowledge base id, the data source id and the documents bucket name

### Requirement: Live retrieval answers the core rights questions in both languages
Against the deployed and ingested knowledge base, retrieval SHALL return relevant passages in the top 5 for these four questions:
- delay compensation at 60 and 120 minutes, asked in English
- the same, asked in German
- the right to a refund, asked in English
- the right to a refund (Erstattung), asked in German

#### Scenario: Compensation in English
- **WHEN** live retrieval asks in English about compensation for a 60- or 120-minute delay
- **THEN** a top-5 passage from `eu-2021-782` mentions both the 25 % and the 50 % compensation levels

#### Scenario: Compensation in German
- **WHEN** live retrieval asks in German about Entschädigung for 60 or 120 minutes of Verspätung, with language `de`
- **THEN** a top-5 passage from `eu-2021-782` or `db-befoerderungsbedingungen` mentions the 25 % or 50 % compensation level

#### Scenario: Refund in German
- **WHEN** live retrieval asks in German about Erstattung of the ticket price, with language `de`
- **THEN** a top-5 passage in German mentions Erstattung

#### Scenario: Refund in English
- **WHEN** live retrieval asks in English about a refund of the ticket price when the journey is cancelled or delayed
- **THEN** a top-5 passage from `eu-2021-782` mentions reimbursement or refund
