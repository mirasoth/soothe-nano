# MemU Configuration System (Simplified Version)

MemU's simplified configuration system: **activity.md is the only required core file**, recording all content. Other files are optional, extracting information from activity.

## 📁 Directory Structure

```
memu/config/
├── __init__.py                 # Configuration module initialization
├── markdown_config.py          # Markdown file configuration (core)
├── prompts/                    # Prompt template directory
│   ├── __init__.py
│   ├── prompt_loader.py
│   ├── agent_activity.txt
│   ├── analyze_session_for_profile.txt
│   ├── analyze_session_for_events.txt
│   ├── analyze_session_for_reminders.txt
│   ├── analyze_session_for_interests.txt
│   ├── analyze_session_for_study.txt
│   └── system_message.txt
└── README.md                   # This document
```

## 🎯 Core Configuration Philosophy

### Simplified Configuration Principles

1. **Activity is the core** - The only required file, recording all conversation and activity content
2. **Everything else is optional** - Extract information from activity, enable as needed
3. **Configuration is simple enough** - No complex dependencies, easy to understand and use
4. **Intelligent auto-detection** - Automatically identify file types and content categories

### `markdown_config.py`

This is the core file of the MemU configuration system, adopting a simplified design:

- **1 required file** - activity.md records all content  
- **5 optional files** - Extract specialized information from activity
- **Simple configuration structure** - Easy to understand and modify
- **Intelligent detection feature** - Automatically categorize markdown files

## 📋 File Type Configuration

### 🔥 Required Files (Core)

#### Activity (activity.md) - 🔥 **Required**
- **Purpose**: Complete record of all conversation and activity content
- **Dependencies**: None (core file, source of all information)
- **Prompt**: `agent_activity.txt`
- **Content**: Complete record of all conversations, activities, thoughts and important information

### ⚙️ Optional Files (Extensions)

The following files are all optional, extracting specific types of information from activity.md:

#### Profile (profile.md) - ⚙️ Optional
- **Purpose**: Extract character basic information from activity
- **Content**: Character basic information profile

#### Events (events.md) - ⚙️ Optional  
- **Purpose**: Extract important event records from activity
- **Content**: Important events and milestones

#### Reminders (reminders.md) - ⚙️ Optional
- **Purpose**: Extract todo items and reminders from activity
- **Content**: Task lists and reminder items

#### Interests (interests.md) - ⚙️ Optional
- **Purpose**: Extract interests and hobbies information from activity
- **Content**: Interests and preference records

#### Study (study.md) - ⚙️ Optional
- **Purpose**: Extract learning-related information from activity
- **Content**: Learning plans and educational goals

## 🔗 Simplified Processing Flow

```
Original conversation → activity.md (required, records all content)
             ↓
          Optional files (extract from activity as needed)
           ├── profile.md
           ├── events.md  
           ├── reminders.md
           ├── interests.md
           └── study.md
```

**Simplified process explanation**:
1. **activity.md** - The only required file, recording all conversation and activity content
2. **Optional files** - All extract information from activity.md, no complex dependencies
3. **Enable as needed** - Choose which optional files to generate based on actual needs

## 🎯 Auto-detection Feature

The configuration system supports automatic file type detection based on filename and content:

### Filename Detection Keywords
- **profile**: profile, bio, character, person, about, personal_info, information
- **event**: event, history, timeline, log, diary, events, milestone
- **reminder**: reminder, todo, task, note, reminders, tasks
- **interests**: interest, hobby, like, preference, interests, hobbies
- **study**: study, learn, course, education, skill, learning, courses
- **activity**: activity, action, summary, diary, record

### Content Pattern Detection
- **profile**: "name:", "age:", "occupation:", "born", "lives in", "personality"
- **event**: "date:", "happened", "occurred", "milestone", "important", "achieved"
- **reminder**: "remember to", "don't forget", "deadline", "due", "urgent"
- **interests**: "likes", "enjoys", "hobby", "interested in", "passion", "favorite"
- **study**: "learning", "studying", "course", "lesson", "skill", "education"
- **activity**: "today", "yesterday", "conversation", "talked", "did", "went"

## 🔧 Simplified Usage

### 1. Basic Configuration Query

```python
from memu.config import get_simple_summary, get_required_files, get_optional_files

# Get simplified configuration summary
summary = get_simple_summary()
print(summary["processing_principle"])  # activity file records all content

# View required and optional files
required = get_required_files()  # ['activity']
optional = get_optional_files()  # ['profile', 'event', 'reminder', 'interests', 'study']
```

### 2. Intelligent File Detection

```python
from memu.config import detect_file_type, is_required_file

# Auto-detect file type
file_type = detect_file_type("activity_log.md")  # Returns 'activity'
file_type = detect_file_type("alice_profile.md")  # Returns 'profile'

# Check if it's a required file
is_core = is_required_file(file_type)  # activity=True, others=False
```

### 3. Practical Usage

```python
from memu import MemoryAgent

# Simplest usage - only need activity file
agent = MemoryAgent(llm_client, memory_dir="memory")

# Auto-import and categorize
agent.import_local_document("notes.md", "Alice")  # Auto-detect file type
```

## 📝 Adding New File Types

To add new markdown file types, please modify the `_load_markdown_configs()` method in `markdown_config.py`:

```python
# Add new file type configuration
configs["new_type"] = MarkdownFileConfig(
    name="new_type",
    filename="new_type.md",
    description="Description of new file type",
    prompt_template="new_type_prompt",
    processing_priority=30,  # Set priority
    depends_on=["activity"],  # Set dependencies
    content_structure={
        "Title1": "## Title1\nContent template",
        "Title2": "## Title2\nContent template",
    },
    usage_examples=["Usage1", "Usage2"],
    auto_detect_keywords=["keyword1", "keyword2"],
    content_patterns=["pattern1", "pattern2"],
)
```

**Also need**:
1. Create corresponding prompt file in `prompts/` directory
2. Update MemoryAgent processing logic (if needed)

## 🚀 Examples and Demos

Run the following command to see a complete demo of the configuration system:

```bash
python examples/config_demo.py
```

This will show:
- All supported file types and descriptions
- Processing order and dependency graph
- Content structure templates
- Auto-detection feature demo
- Configuration validation results

## ⚙️ Advanced Configuration

### Modify Processing Priority

Higher priority values are processed earlier. Current priority allocation:
- activity: 100 (highest)
- profile: 80
- event: 70
- reminder: 60
- interests: 50
- study: 40 (lowest)

### Modify Dependencies

Dependencies ensure files are processed in correct order:
- Depended-upon files must be processed first
- Avoid circular dependencies
- activity is the root dependency for all other files

### Custom Content Structure

You can define standard markdown structure templates for each file type, used for:
- Generating consistent file formats
- Providing user guidance
- Supporting content validation

## 📊 Configuration System Advantages

1. **Centralized management** - All configurations in one file
2. **Easy to extend** - Adding new types only requires modifying configuration
3. **Intelligent detection** - Auto-identify file types
4. **Dependency management** - Ensure correct processing order
5. **Standardization** - Unified file structure and format
6. **Verifiable** - Configuration integrity checks

This configuration system is the core of the MemU architecture, providing a flexible, extensible markdown file management solution. 