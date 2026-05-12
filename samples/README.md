# Sample Data

This directory contains **entirely synthetic** sample documents for testing and demonstrating the Prior Authorization Assistant. These files exercise the system's document extraction, policy matching, and gap analysis capabilities.

## Important Disclaimer

> **All data in this directory is fictional.** No real patient information, protected health information (PHI), or personally identifiable information (PII) is included. Names, member IDs, NPI numbers, dates of birth, and all other identifiers are fabricated for demonstration purposes only.

## Files

### Prior Authorization Requests (FHIR JSON)

| File | Payor | Procedure | Outcome |
|------|-------|-----------|---------|
| `aetna-physical-therapy-pa-approved.json` | Aetna | Physical therapy | Approved |
| `aetna-spinal-fusion-pa-denied.json` | Aetna | Spinal fusion | Denied |
| `anthem-knee-surgery-pa-approved.json` | Anthem | Knee surgery | Approved |
| `humana-cardiac-cath-pa-approved.json` | Humana | Cardiac catheterization | Approved |

### Prior Authorization Requests (PDF)

| File | Payor | Procedure | Outcome |
|------|-------|-----------|---------|
| `aetna-physical-therapy-pa-approved.pdf` | Aetna | Physical therapy | Approved |
| `anthem-knee-surgery-pa-approved.pdf` | Anthem | Knee surgery | Approved |
| `humana-cardiac-cath-pa-approved.pdf` | Humana | Cardiac catheterization | Approved |

## Usage

The application accepts both JSON and PDF inputs:

1. **JSON upload** — Upload any `.json` file through the document upload interface. The system parses the FHIR Bundle directly.
2. **PDF upload** — Upload any `.pdf` file. The system uses document extraction to parse the prior authorization request.
3. The system extracts clinical data, matches it against relevant policies, and produces a gap analysis.
