# Australian Phone Placeholders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show one Australian mobile example in every dedicated Membership phone-entry field.

**Architecture:** Keep all Membership input behavior in the existing single-file React frontend. Replace only the three literal placeholder strings and add a focused static assertion that preserves their exact count and format.

**Tech Stack:** React JSX embedded in `frontend/index.html`; Python `pytest` static frontend checks; Docker Compose frontend image build.

## Global Constraints

- Replace the three dedicated Membership phone-entry placeholders with `+61 412 345 678`.
- Cover registration, staff membership promotion, and staff member editing.
- Leave the mixed email/phone/Member ID login hint unchanged.
- Do not change phone validation, state bindings, request payloads, stored values, or `type="tel"` attributes.

---

### Task 1: Standardize dedicated phone-entry hints

**Files:**
- Modify: `tests/test_frontend_ux_safety.py`
- Modify: `frontend/index.html:3405,3414,3802`

**Interfaces:**
- Consumes: Existing `promotionPhone`, `editForm.phone`, and registration `form.phone` state bindings.
- Produces: The same fields and submitted values, displaying `+61 412 345 678` only when a value is absent.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_frontend_ux_safety.py`:

```python
def test_dedicated_phone_inputs_use_an_australian_example():
    html = read_frontend()

    assert html.count('placeholder="+61 412 345 678" type="tel"') == 2
    assert "{id:'register-phone',label:'Phone',type:'tel',key:'phone',placeholder:'+61 412 345 678'" in html
    assert 'placeholder="+60 12-345 6789"' not in html
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py::test_dedicated_phone_inputs_use_an_australian_example -v`

Expected: FAIL because the current registration field definition uses a Malaysian example and the two staff fields use generic text.

- [ ] **Step 3: Write the minimal implementation**

Replace the two direct staff placeholder attributes in `frontend/index.html` with:

```jsx
placeholder="+61 412 345 678" type="tel"
```

Apply that replacement to the existing promotion and staff-edit inputs. In the existing registration field definition, replace only `placeholder:'+60 12-345 6789'` with `placeholder:'+61 412 345 678'`. Do not change any other attribute or JSX expression.

- [ ] **Step 4: Run focused and regression checks**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py -v`

Expected: PASS, including the new placeholder test and all existing frontend UX safety assertions.

Run: `docker compose build frontend`

Expected: the frontend image builds successfully.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html tests/test_frontend_ux_safety.py
git commit -m "fix: use Australian phone placeholders"
```
