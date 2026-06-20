# Narration Prompts - Version Control System

This directory contains the narration system prompts for video recap generation with full version control.

## Files

- **`narration_prompts.py`** - Main constants file with all prompt versions
- **`README.md`** - This file

## Quick Start

### Using Prompts in Code

```python
from app.prompts.narration_prompts import get_narration_system_prompt

# Get current active prompt (v4 by default)
prompt = get_narration_system_prompt(with_emotion=True)

# Get specific version
prompt_v3 = get_narration_system_prompt(version='v3', with_emotion=True)
```

### View Available Versions

```python
from app.prompts.narration_prompts import get_available_versions

versions = get_available_versions()
for version, info in versions.items():
    print(f"{version}: {info['name']}")
```

### Switch Active Version

```python
from app.prompts.narration_prompts import set_active_prompt_version

# Switch to v3
set_active_prompt_version('v3')
```

## Current Versions

| Version | Name | Date | Status |
|---------|------|------|--------|
| **v4** | Factual Accuracy Enhanced | 2026-06-02 | ✅ Active |
| v3 | Enhanced Storytelling with Structure | 2026-06-02 | Archived |
| v2 | Initial Enhanced Prompt | 2026-06-02 | Archived |
| v1 | Original Prompt | 2026-06-02 | Archived |

## Version Changelog

### v4 (Current)
- ✅ **FACTUAL ACCURACY RULES** - Prevents hallucination and ensures fidelity
- ✅ **CHARACTER REFERENCE POLICY** - Clear priority order for naming
- ✅ **STORYTELLING INTELLIGENCE** - 10 analytical dimensions
- ✅ **NARRATIVE FLOW** - Goal → Obstacle → Action structure
- ✅ **EMOTIONAL DELIVERY** - Matches emotional arc

### v3
- Added CHARACTER REFERENCE POLICY
- Added NARRATIVE FLOW section with connectors
- 10 analytical dimensions
- Structured organization

### v2
- Initial enhanced prompt
- 10 storytelling requirements
- Concrete examples
- Cause-and-effect emphasis

### v1
- Original basic prompt
- 10 analytical dimensions (unstructured)
- Emotional moment matching

## How to Rollback

If the current prompt (v4) causes issues:

1. **In Python code:**
```python
from app.prompts.narration_prompts import set_active_prompt_version
set_active_prompt_version('v3')  # Switch to v3
```

2. **Update the constant:**
```python
# In narration_prompts.py
ACTIVE_PROMPT_VERSION = 'v3'  # Change this line
```

3. **Restart backend:**
```bash
make restart
```

## Adding a New Version

1. **Update `narration_prompts.py`:**
```python
PROMPTS = {
    'v5': {
        'name': 'New Feature Name',
        'date': '2026-06-XX',
        'description': 'What was added/changed',
        'system': """Your new prompt text here""",
        'emotion_addon': """Optional emotion section"""
    },
    # ... other versions
}

ACTIVE_PROMPT_VERSION = 'v5'  # Set as active if ready
```

2. **Restart backend** to pick up changes

3. **Test** the new version with sample recaps

## API Reference

### `get_narration_system_prompt(version=None, with_emotion=False)`

Returns the system prompt for narration generation.

**Parameters:**
- `version` (str, optional): Version to use (v1, v2, v3, v4). Defaults to ACTIVE_PROMPT_VERSION
- `with_emotion` (bool): Include emotion delivery section (default: False)

**Returns:**
- str: The complete system prompt

**Raises:**
- ValueError: If version doesn't exist

### `get_available_versions()`

Returns metadata for all available versions.

**Returns:**
- dict: Version metadata with name, date, description

### `set_active_prompt_version(version)`

Change the active default prompt version.

**Parameters:**
- `version` (str): Version to activate

**Raises:**
- ValueError: If version doesn't exist

## Integration with video_processing.py

The `modules/video_processing.py` file imports and uses prompts:

```python
from app.prompts.narration_prompts import get_narration_system_prompt

# In recap generation function (line ~330):
narr_system = get_narration_system_prompt(with_emotion=bool(emotions_file))
```

This ensures all narration generation automatically uses the active prompt version.

## Testing a New Version

```bash
# 1. Edit narration_prompts.py and set ACTIVE_PROMPT_VERSION to your new version

# 2. Restart backend
make restart

# 3. Create a test recap
# ... upload video and generate recap ...

# 4. Check results for:
# - Accuracy (no invented details)
# - Natural flow (cause-and-effect)
# - Character references (correct or neutral)
# - Emotional tone
# - Word count

# 5. If issues, rollback:
# - Change ACTIVE_PROMPT_VERSION back to v4
# - Restart
```

## Performance Notes

- ✅ No file I/O overhead - All prompts loaded at import time
- ✅ Minimal memory footprint - ~12KB for all versions
- ✅ Fast switching - Can change versions without restarting (just call `set_active_prompt_version()`)
- ✅ Git-friendly - Single Python file makes version history easy to track

## Future Enhancements

- [ ] Analytics tracking for which versions are used
- [ ] A/B testing framework
- [ ] Language-specific prompt variations
- [ ] Prompt performance metrics
