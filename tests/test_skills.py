"""skills: skill folders in a temp global and project directory."""

import unittest
from pathlib import Path

from support import ItemTest

ITEM = "extensions/skills.py"


def write_skill(root, name, description="Use it when releasing.", body="Do the thing.\n", extra=None, front=None):
    folder = Path(root, name)
    folder.mkdir(parents=True, exist_ok=True)
    head = front if front is not None else f"---\nname: {name}\ndescription: {description}\n---\n"
    (folder / "SKILL.md").write_text(head + body)
    for rel, text in (extra or {}).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)
    return folder


class SkillsTest(ItemTest):
    def setUp(self):
        super().setUp()
        self.global_dir = self.tmp / "skills"
        self.work = self.tmp / "work"
        self.project_skills = self.work / ".minimal" / "skills"

    def load_skills(self, **settings):
        registry, errors = self.load(ITEM, global_dir=str(self.global_dir), **settings)
        self.assertEqual(errors, [])
        return registry

    def prompt(self, registry, trusted=True):
        edit = next(e for e in registry.prompt_edits if e.name == "skills")
        return edit.text(self.ctx(cwd=self.work, project_trusted=trusted))

    def test_prompt_index_lists_name_and_description_sorted(self):
        write_skill(self.global_dir, "zeta", "Last one.")
        write_skill(self.global_dir, "alpha", "First one.")
        self.assertEqual(
            self.prompt(self.load_skills()),
            "Skills available (load with the skill tool before relying on them):\n- alpha: First one.\n- zeta: Last one.",
        )

    def test_no_skills_means_no_prompt_section_text(self):
        self.assertIsNone(self.prompt(self.load_skills()))

    def test_skill_tool_returns_body_folder_and_files(self):
        folder = write_skill(self.global_dir, "release", body="Step 1.\nStep 2.\n", extra={"template.md": "t", "scripts/run.sh": "r"})
        registry = self.load_skills()
        out = registry.tools["skill"].run({"name": "release"}, self.ctx(cwd=self.work))
        self.assertEqual(out, f"# release\nFolder: {folder}\n\nStep 1.\nStep 2.\n\nFiles: scripts/run.sh, template.md")
        self.assertTrue(registry.tools["skill"].read_only is True)

    def test_unknown_skill_lists_the_known_ones(self):
        write_skill(self.global_dir, "alpha")
        write_skill(self.global_dir, "beta")
        registry = self.load_skills()
        with self.assertRaisesRegex(ValueError, "^no skill named 'nope'; known skills: alpha, beta$"):
            registry.tools["skill"].run({"name": "nope"}, self.ctx(cwd=self.work))

    def test_project_skills_need_trust_and_win_over_global_ones(self):
        write_skill(self.global_dir, "shared", "Global one.", body="global body\n")
        write_skill(self.project_skills, "shared", "Project one.", body="project body\n")
        write_skill(self.project_skills, "only_here", "Project only.")
        registry = self.load_skills()
        trusted = self.prompt(registry, trusted=True)
        self.assertIn("- shared: Project one.", trusted)
        self.assertIn("- only_here: Project only.", trusted)
        self.assertEqual(self.prompt(registry, trusted=False).splitlines()[1:], ["- shared: Global one."])
        with self.assertRaises(ValueError):
            registry.tools["skill"].run({"name": "only_here"}, self.ctx(cwd=self.work, project_trusted=False))
        self.assertIn("project body", registry.tools["skill"].run({"name": "shared"}, self.ctx(cwd=self.work)))

    def test_invalid_skills_are_skipped_and_reported(self):
        write_skill(self.global_dir, "good")
        write_skill(self.global_dir, "nofront", front="no frontmatter here\n")
        write_skill(self.global_dir, "wrongname", front="---\nname: other\ndescription: x\n---\n")
        write_skill(self.global_dir, "nodesc", front="---\nname: nodesc\n---\n")
        write_skill(self.global_dir, "long", description="x" * 600)
        write_skill(self.global_dir, "unclosed", front="---\nname: unclosed\ndescription: d\n")
        registry = self.load_skills()
        self.assertEqual(self.prompt(registry).splitlines()[1:], ["- good: Use it when releasing."])
        problems = "\n".join(registry.problems)
        self.assertIn("nofront/SKILL.md: it must start with a --- frontmatter block holding name: and description:; skipped", problems)
        self.assertIn("name 'other' must equal the folder name 'wrongname'", problems)
        self.assertIn("nodesc/SKILL.md: description is required: say when the skill applies; skipped", problems)
        self.assertIn("long/SKILL.md: description is 600 characters; the limit is 500; skipped", problems)
        self.assertIn("the frontmatter block is not closed with ---", problems)

    def test_changes_to_a_skill_show_up_without_reload(self):
        write_skill(self.global_dir, "alpha", "Old.")
        registry = self.load_skills()
        self.assertIn("- alpha: Old.", self.prompt(registry))
        path = write_skill(self.global_dir, "alpha", "New description.") / "SKILL.md"
        path.touch()
        self.assertIn("- alpha: New description.", self.prompt(registry))

    def test_max_skills_and_description_chars_settings(self):
        for n in "abc":
            write_skill(self.global_dir, n)
        self.assertEqual(len(self.prompt(self.load_skills(max_skills=2)).splitlines()), 3)
        registry = self.load_skills(description_chars=20)
        self.assertIsNone(self.prompt(registry))
        self.assertTrue(any("the limit is 20" in p for p in registry.problems))

    def test_skills_command_lists_and_shows(self):
        write_skill(self.global_dir, "alpha", "First.")
        registry = self.load_skills()
        ctx = self.ctx(cwd=self.work)
        listing = registry.commands["skills"].run("", ctx)
        self.assertRegex(listing, r"^alpha +First\.  \[.*alpha\]$")
        self.assertIn("# alpha", registry.commands["skills"].run("alpha", ctx))
        self.assertIn("no skill named 'x'", registry.commands["skills"].run("x", ctx))

    def test_disabled_registers_nothing(self):
        registry, _ = self.load(ITEM, enabled=False)
        self.assertEqual((list(registry.commands), [t for t in registry.tools if t == "skill"]), ([], []))


if __name__ == "__main__":
    unittest.main()
