#!/usr/bin/env python3
"""
Extract Alpha Read article data from TimeBack QTI API.
Outputs grade JSON files matching the viewer's expected format.
"""

import json
import subprocess
import sys
import os
import gc
import re
import time

TOKEN_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
CLIENT_ID = "256oicakudnqigtubi80dn9sf5"
CLIENT_SECRET = "non04ind88qeh7ebokgvvi9ohaurj3e5ouvad5qu2o6q1lh1vdu"
POWERPATH_BASE = "https://api.alpha-1edtech.ai/powerpath"
QTI_BASE = "https://qti.alpha-1edtech.ai/api"

COURSES = {
    3: "4c49bc61-61b6-4671-b53d-c5a2701a07ff",
    4: "5356b483-4398-4ec5-828a-db1237892db2",
    5: "8cf5f85e-3efc-425a-af0b-a2be695ee4bd",
    6: "623bea14-b17a-448e-9ebc-9c769cd2b511",
    7: "9fdfabd3-a2c9-4518-a8f0-98b86bf5f5d2",
    8: "64b45846-b325-49ac-860d-42bf3c1d472d",
}


def get_token():
    result = subprocess.run(
        ["curl", "-s", "--max-time", "15",
         "-X", "POST", TOKEN_URL,
         "-H", "Content-Type: application/x-www-form-urlencoded",
         "-d", f"grant_type=client_credentials&client_id={CLIENT_ID}&client_secret={CLIENT_SECRET}"],
        capture_output=True, text=True, timeout=30
    )
    data = json.loads(result.stdout)
    return data["access_token"]


def api_get(url, token, retries=3):
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "25",
                 "-H", f"Authorization: Bearer {token}",
                 url],
                capture_output=True, text=True, timeout=35
            )
            if result.stdout.strip():
                return json.loads(result.stdout)
        except Exception as e:
            print(f"    Retry {attempt+1} for {url.split('/')[-1]}: {e}")
            time.sleep(2)
    return None


def as_dict(val):
    """Normalize API values that may be a dict, list, or other."""
    if isinstance(val, dict):
        return val
    if isinstance(val, list) and val:
        return val[0] if isinstance(val[0], dict) else {}
    return {}


def as_list(val):
    """Normalize API values that may be a dict, list, or other."""
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


def extract_stimulus_html(raw_xml):
    """Extract HTML content from stimulus rawXml."""
    match = re.search(r'<qti-stimulus-body>(.*?)</qti-stimulus-body>', raw_xml, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def extract_stimulus_text(html):
    """Strip HTML tags to get plain text."""
    text = re.sub(r'<[^>]+>', '', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_choice_item(content, response_decls):
    """Parse a choice interaction from QTI content JSON."""
    item_body = content.get("qti-assessment-item", {}).get("qti-item-body", {})
    interaction = item_body.get("qti-choice-interaction", {})
    if isinstance(interaction, list):
        interaction = interaction[0] if interaction else {}

    prompt = interaction.get("qti-prompt", "")
    if isinstance(prompt, dict):
        prompt = prompt.get("_", "")

    # Get correct answer identifier(s)
    correct_ids = set()
    for rd in response_decls:
        cr = rd.get("correctResponse", {})
        vals = cr.get("value", [])
        if isinstance(vals, str):
            vals = [vals]
        correct_ids.update(vals)

    # Parse choices
    simple_choices = as_list(interaction.get("qti-simple-choice", []))

    choices = []
    for sc in simple_choices:
        choice_id = sc.get("_attributes", {}).get("identifier", "")
        choice_text = sc.get("_", "")
        feedback = ""
        fb = sc.get("qti-feedback-inline", {})
        if isinstance(fb, dict):
            feedback = fb.get("_", "")
        elif isinstance(fb, list) and fb:
            feedback = fb[0].get("_", "")

        choices.append({
            "identifier": choice_id,
            "text": choice_text,
            "feedback": feedback,
            "is_correct": choice_id in correct_ids,
        })

    return prompt, "choice", choices, []


def parse_text_entry_item(content, response_decls):
    """Parse a text entry interaction."""
    item_body = content.get("qti-assessment-item", {}).get("qti-item-body", {})

    # Could be qti-text-entry-interaction or qti-extended-text-interaction
    interaction = item_body.get("qti-text-entry-interaction", item_body.get("qti-extended-text-interaction", {}))
    if isinstance(interaction, list):
        interaction = interaction[0] if interaction else {}
    itype = "text_entry" if "qti-text-entry-interaction" in item_body else "extended_text"

    prompt = interaction.get("qti-prompt", "")
    if isinstance(prompt, dict):
        prompt = prompt.get("_", "")

    # Also check for prompt in item body directly
    if not prompt:
        p = item_body.get("p", "")
        if isinstance(p, str):
            prompt = p
        elif isinstance(p, list):
            prompt = " ".join(x if isinstance(x, str) else x.get("_", "") for x in p)

    correct_answers = []
    for rd in response_decls:
        cr = rd.get("correctResponse", {})
        vals = cr.get("value", [])
        if isinstance(vals, str):
            vals = [vals]
        correct_answers.extend(vals)

    return prompt, itype, [], correct_answers


def parse_item(item_data):
    """Parse a QTI assessment item into our viewer JSON format."""
    content = item_data.get("content", {})
    response_decls = item_data.get("responseDeclarations", [])
    item_type = item_data.get("type", "")

    if item_type == "choice" or "qti-choice-interaction" in str(content.get("qti-assessment-item", {}).get("qti-item-body", {}).keys()):
        prompt, itype, choices, correct_answers = parse_choice_item(content, response_decls)
    else:
        prompt, itype, choices, correct_answers = parse_text_entry_item(content, response_decls)

    # Get stimulus ref from content
    stim_ref_data = as_dict(content.get("qti-assessment-item", {}).get("qti-assessment-stimulus-ref", {}))
    stim_id = stim_ref_data.get("_attributes", {}).get("identifier", "")

    return {
        "identifier": item_data.get("identifier", ""),
        "title": item_data.get("title", ""),
        "type": item_type,
        "metadata": item_data.get("metadata", {}),
        "stimulus": None,  # filled in later if stim_id
        "prompt": prompt,
        "interaction_type": itype,
        "choices": choices,
        "correct_answers": correct_answers,
        "stimulus_ref": stim_id or None,
    }


def fetch_stimulus(stim_id, token):
    """Fetch and parse a stimulus."""
    stim_data = api_get(f"{QTI_BASE}/stimuli/{stim_id}", token)
    if not stim_data:
        return None

    raw_xml = stim_data.get("rawXml", "")
    content_html = extract_stimulus_html(raw_xml)
    content_text = extract_stimulus_text(content_html)

    return {
        "identifier": stim_id,
        "title": stim_data.get("title", ""),
        "metadata": stim_data.get("metadata", {}),
        "content_html": content_html,
        "content_text": content_text,
    }


def extract_grade(grade, course_id):
    """Extract all articles for a single grade."""
    print(f"\n{'='*60}")
    print(f"Grade {grade} — Course {course_id}")
    print(f"{'='*60}")

    token = get_token()
    print("Got auth token")

    # Fetch syllabus
    syllabus = api_get(f"{POWERPATH_BASE}/syllabus/{course_id}", token)
    if not syllabus:
        print("ERROR: Could not fetch syllabus")
        return None

    syl = syllabus.get("syllabus", syllabus)
    course_info = syl.get("course", {})
    course_title = course_info.get("title", f"Alpha Read Grade {grade}")
    units_raw = syl.get("subComponents", [])
    print(f"Course: {course_title} — {len(units_raw)} unit(s)")

    # Build flat list of all assessments
    all_articles = []
    for unit in units_raw:
        unit_title = unit.get("title", "Unknown Unit")
        sort_order = unit.get("sortOrder", 0)
        for res in unit.get("componentResources", []):
            resource = res.get("resource", {})
            res_meta = resource.get("metadata", {})
            all_articles.append({
                "unit_title": unit_title,
                "unit_sort": sort_order,
                "identifier": res.get("sourcedId", ""),
                "title": res.get("title", ""),
                "xp": res_meta.get("xp"),
            })

    total = len(all_articles)
    print(f"Total articles: {total}")

    # Process each assessment
    units_map = {}
    question_count = 0

    for idx, article in enumerate(all_articles):
        identifier = article["identifier"]
        print(f"\n  [{idx+1}/{total}] {article['title'] or identifier}", end="", flush=True)

        # Re-auth every 30 articles
        if idx > 0 and idx % 30 == 0:
            print("\n  Re-authenticating...", end="", flush=True)
            token = get_token()

        # Ensure unit exists in map
        unit_key = article["unit_title"]
        if unit_key not in units_map:
            units_map[unit_key] = {
                "title": unit_key,
                "sort_order": article["unit_sort"],
                "assessments": []
            }

        # Fetch assessment test
        test_data = api_get(f"{QTI_BASE}/assessment-tests/{identifier}", token)
        if not test_data:
            print(" — FAILED", end="")
            units_map[unit_key]["assessments"].append({
                "identifier": identifier,
                "error": "Failed to fetch"
            })
            continue

        assessment = {
            "identifier": identifier,
            "title": test_data.get("title", ""),
            "qtiVersion": test_data.get("qtiVersion", ""),
            "metadata": test_data.get("metadata", {}),
            "test_parts": [],
            "syllabus_metadata": {
                "title": article["title"],
                "xp": article["xp"],
            }
        }

        # Parse test parts (API uses qti-test-part key)
        test_parts = as_list(test_data.get("qti-test-part", []))

        for tp in test_parts:
            test_part = {
                "identifier": tp.get("identifier", ""),
                "sections": []
            }

            sections = as_list(tp.get("qti-assessment-section", []))

            for sec in sections:
                section = {
                    "title": sec.get("title", ""),
                    "identifier": sec.get("identifier", ""),
                    "items": []
                }

                item_refs = as_list(sec.get("qti-assessment-item-ref", []))

                for ref in item_refs:
                    item_id = ref.get("identifier", "")
                    if not item_id:
                        href = ref.get("href", "")
                        if href:
                            item_id = href.rstrip("/").split("/")[-1]
                    if not item_id:
                        continue

                    # Fetch item
                    item_data = api_get(f"{QTI_BASE}/assessment-items/{item_id}", token)
                    if not item_data:
                        print(f" !", end="", flush=True)
                        continue

                    parsed = parse_item(item_data)

                    # Fetch stimulus if referenced
                    if parsed["stimulus_ref"]:
                        stim = fetch_stimulus(parsed["stimulus_ref"], token)
                        if stim:
                            parsed["stimulus"] = stim

                    section["items"].append(parsed)
                    question_count += 1

                test_part["sections"].append(section)
            assessment["test_parts"].append(test_part)

        item_count = sum(
            len(sec["items"])
            for tp in assessment["test_parts"]
            for sec in tp["sections"]
        )
        print(f" — {item_count}q", end="", flush=True)
        units_map[unit_key]["assessments"].append(assessment)
        gc.collect()

    # Build output
    units_out = sorted(units_map.values(), key=lambda u: u["sort_order"])
    article_count = sum(
        len(u["assessments"]) for u in units_out
    )
    result = {
        "metadata": {
            "grade": grade,
            "course_title": course_title,
            "course_id": course_id,
            "total_articles": article_count,
            "total_questions": question_count,
            "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "units": units_out
    }

    print(f"\n\n  TOTAL: {article_count} articles, {question_count} questions")
    return result


def main():
    grade = int(sys.argv[1]) if len(sys.argv) > 1 else None
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(output_dir, exist_ok=True)

    grades_to_extract = [grade] if grade else [3, 4, 5, 6, 7, 8]

    for g in grades_to_extract:
        course_id = COURSES[g]
        result = extract_grade(g, course_id)
        if result:
            outpath = os.path.join(output_dir, f"grade{g}.json")
            with open(outpath, "w") as f:
                json.dump(result, f)
            size_mb = os.path.getsize(outpath) / (1024 * 1024)
            print(f"Saved {outpath} ({size_mb:.1f} MB)")
        gc.collect()


if __name__ == "__main__":
    main()
