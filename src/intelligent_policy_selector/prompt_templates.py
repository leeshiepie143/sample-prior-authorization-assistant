"""
Prompt templates for intelligent policy selection using Bedrock Knowledge Base.
"""

from string import Template

def create_policy_selection_prompt(
    payor: str,
    service_codes: list,
    service_descriptions: dict,
    icd_codes: list,
    icd_descriptions: dict,
    service_type: str,
    patient_age_range: str,
    patient_gender: str,
    primary_diagnosis: str,
    comorbidities: list
) -> str:
    """
    Create a comprehensive prompt for KB-based policy selection.
    
    This prompt instructs the KB to:
    1. Evaluate all relevant policies for the payor
    2. Compare policies based on multiple factors
    3. Select the single best-fit policy
    4. Return structured output with S3 URI, rationale, and confidence
    
    Args:
        service_codes: Combined list of all service codes (CPT, HCPCS, RxNorm)
        service_descriptions: Dict mapping codes to descriptions
        icd_codes: List of ICD diagnosis codes
        icd_descriptions: Dict mapping ICD codes to descriptions
    """
    
    # Format service codes with descriptions
    # AI can distinguish CPT/HCPCS/RxNorm by code format and description
    service_codes_formatted = []
    if service_codes:
        for code in service_codes:
            if service_descriptions and code in service_descriptions:
                service_codes_formatted.append(f"{code} ({service_descriptions[code]})")
            else:
                service_codes_formatted.append(code)
    
    service_codes_str = ", ".join(service_codes_formatted) if service_codes_formatted else "None specified"
    
    # Format ICD codes with descriptions
    icd_codes_formatted = []
    if icd_codes:
        for code in icd_codes:
            if icd_descriptions and code in icd_descriptions:
                icd_codes_formatted.append(f"{code} ({icd_descriptions[code]})")
            else:
                icd_codes_formatted.append(code)
    
    icd_codes_str = ", ".join(icd_codes_formatted) if icd_codes_formatted else "None specified"
    comorbidities_str = ", ".join(comorbidities) if comorbidities else "None"
    
    _SELECTION_TEMPLATE = Template(
        """You are an expert medical policy analyst tasked with selecting the SINGLE MOST APPROPRIATE medical necessity policy for a prior authorization request.

## PATIENT CONTEXT
- **Payor**: $payor
- **Requested Services**: $service_codes_str
- **Diagnoses**: $icd_codes_str
- **Service Type**: $service_type
- **Patient Age**: $patient_age_range
- **Patient Gender**: $patient_gender
- **Primary Diagnosis**: $primary_diagnosis
- **Comorbidities**: $comorbidities_str

## YOUR TASK
Evaluate ALL available policies for $payor and select the SINGLE BEST policy that:
1. **Covers the requested services** (codes and procedures listed above)
2. **Aligns with the patient's diagnoses** (ICD codes and conditions listed above)
3. **Matches the service type** ($service_type)
4. **Is appropriate for the patient demographics** (age: $patient_age_range, gender: $patient_gender)
5. **Has the most current effective date** (prefer newer policies)

## EVALUATION CRITERIA (in order of importance)
1. **Service Coverage**: Policy explicitly covers the requested services, either by exact code match OR by code range that includes the requested codes
2. **Diagnosis Alignment**: Policy covers the patient's diagnoses and clinical conditions
3. **Service Type Relevance**: Policy is specific to $service_type
4. **Clinical Appropriateness**: Policy criteria align with patient's clinical presentation
5. **Policy Recency**: Most recent effective date (prefer policies from 2024-2025)
6. **Specificity**: More specific policies preferred over generic ones

## COMPARISON PROCESS
1. Review all policies retrieved from the knowledge base
2. For each policy, assess coverage of requested services and diagnoses
3. Compare policies side-by-side on the evaluation criteria above
4. Identify the policy with the strongest overall match
5. Verify the selected policy is appropriate for the patient's demographics

## IMPORTANT NOTES ON CODE MATCHING
- **Service Code Types**: Codes may be procedure codes (5-digit numbers like 93458), equipment codes (letter+numbers like K0005), or medication codes (longer numbers like 1551291). The descriptions clarify what each represents.
- **Code Ranges**: Policies often specify code ranges (e.g., "93600-93603" or "CPT codes 93600 through 93603"). A discrete code falls within a range if it's numerically between the start and end codes. For example:
  - Patient code "93601" MATCHES policy range "93600-93603"
  - Patient code "93458" MATCHES policy range "93450-93460"
  - Patient code "K0005" MATCHES policy range "K0001-K0010"
- **Exact vs Range Matching**: Both exact code matches and range matches are valid. Consider a policy that covers the code range as equally valid as one that lists the exact code.

## OUTPUT FORMAT (OPTIONAL - FOR CONTEXT ONLY)
You may optionally return your analysis in JSON format:

```json
{{
  "confidence_score": 0.95,
  "selection_rationale": "Concise explanation (2-3 sentences) of why this policy is the best match. Include: (1) how it covers the requested service codes, (2) how it aligns with the patient's diagnoses, (3) why it's clinically appropriate."
}}
```

**Note**: The system will automatically use the most relevant policy from the knowledge base search results. Your analysis helps explain the selection but is not required.

## IMPORTANT INSTRUCTIONS
- **Confidence Score**: Range 0.0-1.0. Use 0.9+ for exact matches, 0.7-0.9 for strong matches, 0.5-0.7 for partial matches, <0.5 for weak matches.
- **Concise Rationale**: Keep the rationale focused and brief (2-3 sentences maximum).
- **Focus on Evaluation**: Explain why the top policy is most appropriate for this case.
## EDGE CASES
- **No Exact Match**: If no policy exactly matches all services, select the policy with the best partial match and explain the gaps.
- **Multiple Equivalent Policies**: If multiple policies are equally good, select the most recent one.
- **Conflicting Information**: If policies conflict, prefer the policy with the most specific criteria for this service type.
- **Mixed Service Types**: If request includes multiple service types (e.g., procedure + medication), select the policy that covers the primary service.

Now, evaluate the available policies and select the SINGLE BEST policy for this prior authorization request.
"""
    )
    prompt = _SELECTION_TEMPLATE.substitute(
        payor=payor,
        service_codes_str=service_codes_str,
        icd_codes_str=icd_codes_str,
        service_type=service_type,
        patient_age_range=patient_age_range,
        patient_gender=patient_gender,
        primary_diagnosis=primary_diagnosis,
        comorbidities_str=comorbidities_str
    )
    
    return prompt


def create_criteria_extraction_prompt(
    policy_content: str,
    payor: str,
    service_codes: list,
    icd_codes: list,
    service_type: str
) -> str:
    """
    Create a prompt for extracting clinical criteria from the selected policy.
    
    This is used AFTER policy selection to extract detailed criteria.
    """
    
    service_codes_str = ", ".join(service_codes) if service_codes else "None"
    icd_codes_str = ", ".join(icd_codes) if icd_codes else "None"
    
    prompt = f"""You are a medical policy analyst extracting clinical criteria from a medical necessity policy.

## POLICY CONTEXT
- **Payor**: {payor}
- **Service Codes**: {service_codes_str}
- **Diagnosis Codes**: {icd_codes_str}
- **Service Type**: {service_type}

## POLICY CONTENT
{policy_content}

## YOUR TASK
Extract ALL clinical criteria that must be met for this service to be medically necessary. For each criterion:
1. Identify the specific requirement
2. List the required evidence types
3. Note any clinical indicators
4. Identify exclusion criteria

## OUTPUT FORMAT
Return a JSON array of clinical criteria:

```json
[
  {{
    "criterion_id": "crit_001",
    "title": "Brief title (3-8 words, NOT the full description)",
    "description": "Complete, detailed description of the requirement",
    "required_evidence": [
      "Specific type of evidence needed (e.g., 'Diagnostic imaging showing stenosis')",
      "Another evidence type"
    ],
    "clinical_indicators": [
      "Clinical sign or symptom that supports this criterion",
      "Another indicator"
    ],
    "exclusion_criteria": [
      "Condition or circumstance that would exclude this criterion",
      "Another exclusion"
    ],
    "priority": "required" | "preferred" | "optional"
  }}
]
```

## EXTRACTION RULES
1. **Be Specific**: Extract exact requirements, not paraphrased versions
2. **Separate Criteria**: Each distinct requirement should be a separate criterion
3. **Include Context**: Reference specific service codes or diagnoses when mentioned
4. **Priority Classification**:
   - "required": MUST be met for approval
   - "preferred": Strongly recommended but not absolute
   - "optional": Nice to have but not necessary
5. **Evidence Types**: Be specific (e.g., "MRI showing lesion" not just "imaging")


Extract all criteria now.
"""
    
    return prompt
