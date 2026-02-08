# Bulk Rename Tool

This is a tool that:
- Reads a list of files on stdin
- Applies regex-replacements on each file name (not the directory portion)
- Interactively prompts the user to confirm each change
- Renames the files
- Note: does not move the files, only renames them in place, leaving the directory names alone

## Usage Examples:
```bash
# Basic usage, note the regex and replacement are consecutive args, captures referenced with `$1`, `$2` etc.
$ find . -name '*.mp4' | bulk-rename '[-_]+' '_'

# Can have multiple regex-replacements
$ find . -name '*.mp4' | bulk-rename '[-_]+' '_'  '\.mp4$' ''

# Can separate filenames by \0 instead of \n
$ find . -name '*.mp4' -print0 | bulk-rename -0 '[-_]+' '_'  '\.mp4$' ''

# Can automatically replace strings of non-alphanumeric characters with a single underscore (applies _after_ all user-given regex-replacements)
$ find . -name '*.mp4' | bulk-rename -alpha 'Ex.ra' ''

# Can automatically place an `n`-digit number at the front of each filename (applies _after_ all user-given regex-replacements)
$ find . -name '*.mp4' | bulk-rename -num 3 'Ex.ra' ''  # 3-digit numbers 001, 002, etc.

# Can truncate the filename to a fixed length (applies _after_ all user-given regex-replacements) (length does _not_ include the extension or directory portion)
$ find . -name '*.mp4' | bulk-rename -truncate 10 'Ex.ra' ''  # Truncate to 10 characters
```

## Command Line Options:
- `-0`: Use \0 as the separator between filenames instead of \n
- `-alpha`: Automatically replace strings of non-alphanumeric characters with a single underscore (applies _after_ all user-given regex-replacements)
- `-num <n>`: Automatically place an incrementing `<n>`-digit number at the front of each filename (applies _after_ all user-given regex-replacements)
- `-truncate <n>`: Truncate the filename to a fixed length (applies _after_ all user-given regex-replacements) (length does _not_ include the extension or directory portion)
- `-y`: Do not prompt the user to confirm each change
- `<regex>,<replacement>`: Apply the regex-replacement to each filename (optional, can be specified multiple times)

## Confirmation Workflow:
- The tool prints the old and new filename to stderr
- The tool allows the following responses:
  - `y`: Yes, rename this file
  - `n`: No, do not rename this file
  - `a`: Yes, rename this file and all remaining files
  - `q`: Quit, do not rename this file or any remaining files

## Exit Status:
- 0: Success
- 1: Error

## License:
MIT

