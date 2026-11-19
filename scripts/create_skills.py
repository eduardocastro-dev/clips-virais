"""Synchronize project skills between .agents/skills and .claude/skills."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent.parent
source = root / '.agents' / 'skills'
target = root / '.claude' / 'skills'

target.mkdir(parents=True, exist_ok=True)
count = 0
for folder in source.iterdir():
    if folder.is_dir() and (folder / 'SKILL.md').is_file():
        dest = target / folder.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / 'SKILL.md', dest / 'SKILL.md')
        count += 1

print(f'{count} skills synchronized between .agents/skills and .claude/skills.')
