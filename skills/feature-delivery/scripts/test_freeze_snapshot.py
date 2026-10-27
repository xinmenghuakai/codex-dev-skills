#!/usr/bin/env python3
"""freeze_snapshot.py 的确定性回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from freeze_snapshot import (
    load_and_verify_snapshot,
    parse_absolute_literal_path,
    write_new_json,
)
import freeze_snapshot as freeze_snapshot_module


SCRIPT = Path(__file__).with_name("freeze_snapshot.py")


class PrebuiltReleaseTest(unittest.TestCase):
    """在临时仓库模拟预构建候选和远端 ref，绝不进行网络推送或真实构建。"""

    def test_two_repositories_can_publish_serially_without_claiming_global_success(self):
        """本仓可以先校验；默认全范围、未知仓库和多仓混报仍被拒绝。"""
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repos = [directory / "backend", directory / "frontend"]

            def git(repo, *args):
                """只操作隔离测试仓库的本地对象与引用。"""
                return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()

            def cli(*args):
                """记录校验退出码，不执行任何真实远端请求。"""
                return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, check=False)

            freeze_args = []
            for repo in repos:
                repo.mkdir()
                git(repo, "init", "-q", "-b", "main")
                git(repo, "config", "user.email", "skill-test@example.invalid")
                git(repo, "config", "user.name", "Skill Test")
                (repo / "app.txt").write_text("base\n")
                git(repo, "add", "app.txt")
                git(repo, "commit", "-qm", "base")
                git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
                git(repo, "switch", "-qc", "candidate")
                (repo / "app.txt").write_text("reviewed\n")
                git(repo, "add", "app.txt")
                git(repo, "commit", "-qm", "candidate")
                freeze_args.extend(("--repo-target", f"{repo}=refs/remotes/origin/main"))
            snapshot, binding = directory/"snapshot.json", directory/"binding.json"
            frozen = cli(*freeze_args, "--output", str(snapshot))
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            bound = cli("--bind-release-snapshot", str(snapshot), "--output", str(binding))
            self.assertEqual(bound.returncode, 0, bound.stderr)

            for repo in repos:
                git(repo, "switch", "-q", "main")
                git(repo, "merge", "--no-ff", "candidate", "-m", "merge candidate")
                args = ("--verify-release-binding", str(binding), "--release-commit", f"{repo}=HEAD")
                full_missing = cli(*args, "--before-push")
                self.assertNotEqual(full_missing.returncode, 0)
                self.assertIn("exactly cover every", full_missing.stderr)
                before = cli(*args, "--before-push", "--per-repository")
                self.assertEqual(before.returncode, 0, before.stderr)
                self.assertIn("repository only=", before.stdout)
                git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
                after = cli(*args, "--per-repository")
                self.assertEqual(after.returncode, 0, after.stderr)
            all_args = ["--verify-release-binding", str(binding)]
            for repo in repos:
                all_args.extend(("--release-commit", f"{repo}=HEAD"))
            all_verified = cli(*all_args)
            self.assertEqual(all_verified.returncode, 0, all_verified.stderr)
            multi_partial = cli(*all_args, "--per-repository")
            self.assertNotEqual(multi_partial.returncode, 0)
            self.assertIn("exactly one bound", multi_partial.stderr)
            foreign = directory / "foreign"
            foreign.mkdir()
            git(foreign, "init", "-q", "-b", "main")
            unknown = cli("--verify-release-binding", str(binding), "--release-commit", f"{foreign}=HEAD", "--per-repository")
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("exactly one bound", unknown.stderr)

    def test_prebuilt_artifact_verified_before_push_then_remote_readback(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repo = directory / "repo"
            repo.mkdir()

            def git(*args):
                """Git 操作仅限本测试创建的仓库。"""
                return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()

            def cli(*args):
                """执行只读校验或临时证据生成，并保留退出码供断言。"""
                return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, check=False)

            git("init", "-q", "-b", "main")
            git("config", "user.email", "skill-test@example.invalid")
            git("config", "user.name", "Skill Test")
            (repo / "source.js").write_text("base\n")
            git("add", "source.js")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            # 仅本地创建远端跟踪 ref，模拟实际 origin/main 在推送前尚未推进。
            git("update-ref", "refs/remotes/origin/main", base)
            git("switch", "-qc", "candidate")
            (repo / "source.js").write_text("changed source\n")
            (repo / "home").mkdir()
            (repo / "home/app.js").write_text("prebuilt reviewed artifact\n")
            git("add", "source.js", "home/app.js")
            git("commit", "-qm", "candidate including build artifact")
            candidate = git("rev-parse", "HEAD")
            snapshot, binding = directory/"snapshot.json", directory/"binding.json"
            frozen = cli("--repo-target", f"{repo}=refs/remotes/origin/main", "--output", str(snapshot))
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            bound = cli("--bind-release-snapshot", str(snapshot), "--output", str(binding))
            self.assertEqual(bound.returncode, 0, bound.stderr)
            git("switch", "-q", "main")
            git("merge", "--no-ff", "candidate", "-m", "merge reviewed candidate")
            merge = git("rev-parse", "HEAD")
            args = ("--verify-release-binding", str(binding), "--release-commit", f"{repo}=HEAD")
            before = cli(*args, "--before-push")
            self.assertEqual(before.returncode, 0, before.stderr)
            self.assertIn("local only", before.stdout)
            not_published = cli(*args)
            self.assertNotEqual(not_published.returncode, 0)
            self.assertIn("current bound target HEAD", not_published.stderr)

            # 未经审查的远端推进即使不触碰产物也必须阻断推送前验证。
            drift = git("commit-tree", f"{base}^{{tree}}", "-p", base, "-m", "concurrent remote change")
            git("update-ref", "refs/remotes/origin/main", drift)
            rejected = cli(*args, "--before-push")
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("drifted before push", rejected.stderr)
            git("update-ref", "refs/remotes/origin/main", base)
            wrong_head = cli("--verify-release-binding", str(binding), "--release-commit", f"{repo}={candidate}", "--before-push")
            self.assertNotEqual(wrong_head.returncode, 0)
            self.assertIn("local HEAD", wrong_head.stderr)

            # 模拟成功推送后 fetch 读回，普通后验仍严格要求目标 ref 等于合并提交。
            git("update-ref", "refs/remotes/origin/main", merge)
            after = cli(*args)
            self.assertEqual(after.returncode, 0, after.stderr)
            (repo / "home/app.js").write_text("unreviewed rebuild\n")
            git("add", "home/app.js")
            git("commit", "-qm", "unexpected target rebuild")
            extra = cli(*args, "--before-push")
            self.assertNotEqual(extra.returncode, 0)


class FreezeSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        directory = Path(cls._temp.name)
        cls.repo = directory / "repo"
        cls.repo.mkdir()
        for arguments in (
            ("init", "-q"),
            ("config", "user.email", "skill-test@example.invalid"),
            ("config", "user.name", "Skill Test"),
        ):
            subprocess.run(["git", "-C", str(cls.repo), *arguments], check=True)
        cls.tracked = cls.repo / "tracked.txt"
        cls.tracked.write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(cls.repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(cls.repo), "commit", "-qm", "base"], check=True)
        cls.target_ref = subprocess.run(
            ["git", "-C", str(cls.repo), "symbolic-ref", "-q", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        cls.artifact = directory / "plan.md"
        cls.artifact.write_text("# plan\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def freeze(self, filename: str) -> Path:
        output = Path(self._temp.name) / filename
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--repo-target",
                f"{self.repo}={self.target_ref}",
                "--artifact",
                str(self.artifact),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return output

    def test_snapshot_recomputes_git_and_artifact_content(self) -> None:
        self.tracked.write_text("reviewed\n", encoding="utf-8")
        snapshot = self.freeze("reviewed-snapshot.json")
        _, fingerprint = load_and_verify_snapshot(snapshot)
        self.assertEqual(len(fingerprint), 64)

        self.tracked.write_text("changed-after-review\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            load_and_verify_snapshot(snapshot)

    def test_snapshot_rejects_new_untracked_file(self) -> None:
        self.tracked.write_text("reviewed-again\n", encoding="utf-8")
        snapshot = self.freeze("untracked-snapshot.json")
        (self.repo / "new.txt").write_text("untracked\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            load_and_verify_snapshot(snapshot)

    def test_snapshot_rejects_changed_artifact(self) -> None:
        self.tracked.write_text("reviewed-third\n", encoding="utf-8")
        snapshot = self.freeze("artifact-snapshot.json")
        self.artifact.write_text("# changed plan\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            load_and_verify_snapshot(snapshot)

    def test_snapshot_keeps_file_level_range_evidence(self) -> None:
        self.artifact.write_text("# plan stable\n", encoding="utf-8")
        self.tracked.write_text("reviewed range\n", encoding="utf-8")
        snapshot_path = self.freeze("file-level.json")
        snapshot, _ = load_and_verify_snapshot(snapshot_path)

        self.assertEqual(snapshot["schema_version"], 4)
        tracked_entry = next(
            item
            for item in snapshot["repositories"][0]["files"]
            if item["path"] == "tracked.txt"
        )
        self.assertEqual(tracked_entry["kind"], "regular")
        self.assertEqual(len(snapshot["repositories"][0]["diff_sha256"]), 64)

    def test_snapshot_records_target_candidate_and_true_merge_base(self) -> None:
        self.tracked.write_text("immutable base range\n", encoding="utf-8")
        snapshot_path = self.freeze("immutable-base.json")
        snapshot, _ = load_and_verify_snapshot(snapshot_path)
        base_revision = snapshot["repositories"][0]["base_revision"]
        self.assertRegex(base_revision, r"^[a-f0-9]{40}$")
        self.assertEqual(snapshot["repositories"][0]["target_ref"], self.target_ref)
        self.assertRegex(snapshot["repositories"][0]["target_revision"], r"^[a-f0-9]{40}$")
        self.assertRegex(snapshot["repositories"][0]["candidate_revision"], r"^[a-f0-9]{40}$")

        subprocess.run(
            ["git", "-C", str(self.repo), "add", "tracked.txt"], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-qm", "reviewed change"],
            check=True,
        )
        # Review snapshot 必须绑定当时的候选 HEAD；提交后应走 release binding，
        # 不能把新 commit 当作旧工作树快照自动复用。
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            load_and_verify_snapshot(snapshot_path)

    def test_snapshot_new_file_is_independent_of_git_index_state(self) -> None:
        (self.repo / "index-stable.txt").write_text("same bytes\n", encoding="utf-8")
        snapshot_path = self.freeze("index-stable.json")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "index-stable.txt"], check=True
        )
        load_and_verify_snapshot(snapshot_path)

    def test_snapshot_tracks_symlink_target_text_not_target_file_content(self) -> None:
        target_one = self.repo / "target-one.txt"
        target_two = self.repo / "target-two.txt"
        target_one.write_text("same content\n", encoding="utf-8")
        target_two.write_text("same content\n", encoding="utf-8")
        link = self.repo / "release-link"
        link.symlink_to(target_one.name)
        snapshot_path = self.freeze("symlink.json")
        link.unlink()
        link.symlink_to(target_two.name)
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            load_and_verify_snapshot(snapshot_path)

    def test_snapshot_rejects_git_subdirectory_as_repository_base(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir(exist_ok=True)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--repo-target",
                f"{nested}={self.target_ref}",
                "--artifact",
                str(self.artifact),
                "--output",
                str(Path(self._temp.name) / "subdir.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git worktree root", result.stderr)

    def test_snapshot_output_is_exclusive(self) -> None:
        self.freeze("exclusive.json")
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--repo-target",
                f"{self.repo}={self.target_ref}",
                "--artifact",
                str(self.artifact),
                "--output",
                str(Path(self._temp.name) / "exclusive.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("will not be overwritten", result.stderr)

    def test_evidence_roles_cannot_be_frozen_inside_release_repository(self) -> None:
        for role in ("review_report", "validation_evidence"):
            artifact = self.repo / f"{role}.json"
            artifact.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--repo-target",
                    f"{self.repo}={self.target_ref}",
                    "--artifact",
                    f"{role}={artifact}",
                    "--output",
                    str(Path(self._temp.name) / f"internal-{role}.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"{role} artifact must stay outside", result.stderr)

    def test_safe_evidence_writer_rejects_symlink_parent(self) -> None:
        physical_parent = Path(self._temp.name) / "physical-evidence"
        physical_parent.mkdir()
        symlink_parent = Path(self._temp.name) / "linked-evidence"
        symlink_parent.symlink_to(physical_parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "cannot safely open evidence output parent"):
            write_new_json(symlink_parent / "gate.json", {"ok": True})

    def test_safe_evidence_writer_rejects_ancestor_swapped_after_literal_parse(self) -> None:
        """模拟 Gate 已解析输出参数后，中间祖先才被换成指向发布树的软链。"""
        release_root = Path(self._temp.name) / "release-root"
        (release_root / "nested").mkdir(parents=True)
        evidence_root = Path(self._temp.name) / "evidence-root"
        (evidence_root / "nested").mkdir(parents=True)
        output = parse_absolute_literal_path(str(evidence_root / "nested" / "gate.json"))

        evidence_root.rename(Path(self._temp.name) / "evidence-root-before-swap")
        evidence_root.symlink_to(release_root, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "cannot safely open evidence output parent"):
            write_new_json(output, {"ok": True}, forbidden_roots=(release_root,))
        self.assertFalse((release_root / "nested" / "gate.json").exists())

    def test_safe_evidence_writer_rechecks_open_parent_after_move_into_release_root(self) -> None:
        """已打开目录被并发移动进仓库时，inode 祖先复核仍必须阻止写入。"""
        release_root = Path(self._temp.name) / "release-root-for-move"
        release_root.mkdir()
        evidence_root = Path(self._temp.name) / "evidence-root-for-move"
        output_parent = evidence_root / "nested"
        output_parent.mkdir(parents=True)
        output = parse_absolute_literal_path(str(output_parent / "gate.json"))
        moved_parent = release_root / "moved-evidence"
        real_open = freeze_snapshot_module._open_safe_output_parent

        def move_after_open(path: Path) -> int:
            descriptor = real_open(path)
            output_parent.rename(moved_parent)
            return descriptor

        with mock.patch.object(
            freeze_snapshot_module,
            "_open_safe_output_parent",
            side_effect=move_after_open,
        ):
            with self.assertRaisesRegex(ValueError, "must stay outside release repositories"):
                write_new_json(output, {"ok": True}, forbidden_roots=(release_root,))
        self.assertFalse((moved_parent / "gate.json").exists())

    def test_safe_evidence_writer_holds_original_release_root_fd_across_path_swap(self) -> None:
        """仓库路径被 rename/recreate 后，复核仍必须针对最初固定的仓库 inode。"""
        release_root = Path(self._temp.name) / "release-root-for-path-swap"
        release_root.mkdir()
        evidence_root = Path(self._temp.name) / "evidence-root-for-path-swap"
        output_parent = evidence_root / "nested"
        output_parent.mkdir(parents=True)
        output = parse_absolute_literal_path(str(output_parent / "gate.json"))
        moved_parent = release_root / "moved-evidence"
        original_release_root = Path(self._temp.name) / "release-root-before-swap"
        real_open = freeze_snapshot_module._open_safe_output_parent

        def swap_release_path_after_open(path: Path) -> int:
            descriptor = real_open(path)
            output_parent.rename(moved_parent)
            release_root.rename(original_release_root)
            release_root.mkdir()
            return descriptor

        with mock.patch.object(
            freeze_snapshot_module,
            "_open_safe_output_parent",
            side_effect=swap_release_path_after_open,
        ):
            with self.assertRaisesRegex(ValueError, "must stay outside release repositories"):
                write_new_json(output, {"ok": True}, forbidden_roots=(release_root,))
        self.assertFalse((original_release_root / "moved-evidence" / "gate.json").exists())

    def test_safe_evidence_writer_keeps_replacement_after_post_link_recheck_failure(self) -> None:
        """post-link 复核失败时保留现场，绝不 unlink 并发替换的最终文件。"""
        parent = Path(self._temp.name) / "replacement-parent"
        parent.mkdir()
        output = parent / "gate.json"
        real_assert = freeze_snapshot_module._assert_output_parent_outside_release_repositories
        calls = 0

        def replace_final_before_post_check(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                output.unlink()
                output.write_text("replacement", encoding="utf-8")
                raise ValueError("forced post-link containment failure")
            real_assert(*args, **kwargs)

        with mock.patch.object(
            freeze_snapshot_module,
            "_assert_output_parent_outside_release_repositories",
            side_effect=replace_final_before_post_check,
        ):
            with self.assertRaisesRegex(ValueError, "forced post-link containment failure"):
                write_new_json(output, {"ok": True})
        self.assertEqual(output.read_text(encoding="utf-8"), "replacement")

    def test_safe_evidence_writer_keeps_replacement_of_temporary_name(self) -> None:
        """异常清理临时名时，也不能删除并发替换进去的其他文件。"""
        parent = Path(self._temp.name) / "temporary-replacement-parent"
        parent.mkdir()
        output = parent / "gate.json"
        temporary = parent / ".gate.json.fixed-token.tmp"

        def replace_temporary_then_fail(*args: object, **kwargs: object) -> None:
            temporary.unlink()
            temporary.write_text("replacement", encoding="utf-8")
            raise OSError("forced link failure")

        with mock.patch.object(
            freeze_snapshot_module.secrets, "token_hex", return_value="fixed-token"
        ), mock.patch.object(
            freeze_snapshot_module.os,
            "link",
            side_effect=replace_temporary_then_fail,
        ):
            with self.assertRaisesRegex(ValueError, "cannot safely write evidence output"):
                write_new_json(output, {"ok": True})
        self.assertEqual(temporary.read_text(encoding="utf-8"), "replacement")

    def test_safe_evidence_writer_rejects_temporary_source_replacement_before_link(self) -> None:
        """临时路径在 link 前被替换时，不能把替代物发布成 Gate evidence。"""
        parent = Path(self._temp.name) / "temporary-source-parent"
        parent.mkdir()
        output = parent / "gate.json"
        temporary = parent / ".gate.json.fixed-token.tmp"
        real_link = freeze_snapshot_module.os.link

        def replace_temporary_then_link(*args: object, **kwargs: object) -> None:
            temporary.unlink()
            temporary.write_text("replacement", encoding="utf-8")
            real_link(*args, **kwargs)

        with mock.patch.object(
            freeze_snapshot_module.secrets, "token_hex", return_value="fixed-token"
        ), mock.patch.object(
            freeze_snapshot_module.os,
            "link",
            side_effect=replace_temporary_then_link,
        ):
            with self.assertRaisesRegex(ValueError, "evidence output changed while publishing"):
                write_new_json(output, {"ok": True})
        self.assertEqual(output.read_text(encoding="utf-8"), "replacement")

    def test_snapshot_output_cannot_pollute_release_repository(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--repo-target",
                f"{self.repo}={self.target_ref}",
                "--artifact",
                str(self.artifact),
                "--output",
                str(self.repo / "snapshot.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must stay outside release repositories", result.stderr)

    def test_target_ref_captures_feature_commits_and_rejects_head_as_base(self) -> None:
        """不能靠 repo-base=HEAD 排除 feature branch 上已提交、待发布的改动。"""
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repo = directory / "feature-repo"
            repo.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repo), *arguments], check=True)
            target_ref = subprocess.run(
                ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            source = repo / "service.go"
            source.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run(["git", "-C", str(repo), "switch", "-qc", "feature"], check=True)
            source.write_text("feature commit\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "feature"], check=True)

            snapshot_path = directory / "snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--repo-target",
                    f"{repo}={target_ref}",
                    "--output",
                    str(snapshot_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot, _ = load_and_verify_snapshot(snapshot_path)
            self.assertEqual(snapshot["repositories"][0]["target_ref"], target_ref)
            self.assertEqual(
                [entry["path"] for entry in snapshot["repositories"][0]["files"]],
                ["service.go"],
            )

            rejected = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--repo-base",
                    f"{repo}=HEAD",
                    "--output",
                    str(directory / "unsafe-head.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("target ref must name", rejected.stderr)

    def test_release_binding_rejects_staged_tree_drift_and_verifies_no_ff_merge(self) -> None:
        """Review 工作树和将提交 index 不同，或目标多出额外 commit 时均不得通过。"""
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repo = directory / "release-repo"
            repo.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repo), *arguments], check=True)
            target_ref = subprocess.run(
                ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            source = repo / "service.go"
            source.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run(["git", "-C", str(repo), "switch", "-qc", "feature"], check=True)

            source.write_text("reviewed A\n", encoding="utf-8")
            snapshot_path = directory / "review-snapshot.json"
            freeze = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--repo-target",
                    f"{repo}={target_ref}",
                    "--output",
                    str(snapshot_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stderr)

            # index 暂存 B、工作树恢复 A；旧实现会只重验工作树而允许实际提交 B。
            source.write_text("unreviewed B\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            source.write_text("reviewed A\n", encoding="utf-8")
            binding_path = directory / "release-binding.json"
            mismatch = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--bind-release-snapshot",
                    str(snapshot_path),
                    "--output",
                    str(binding_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("index tree does not exactly match", mismatch.stderr)

            # 重新暂存已审 A，创建 binding，再走真实 no-ff merge 和后验。
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            bound = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--bind-release-snapshot",
                    str(snapshot_path),
                    "--output",
                    str(binding_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            self.assertEqual(binding["schema_version"], 1)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "reviewed A"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "switch", "-q", target_ref.removeprefix("refs/heads/")],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "merge", "--no-ff", "feature", "-m", "merge feature"],
                check=True,
            )
            verified = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--verify-release-binding",
                    str(binding_path),
                    "--release-commit",
                    f"{repo}={target_ref}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)

            source.write_text("extra target commit\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "extra target"], check=True)
            extra = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--verify-release-binding",
                    str(binding_path),
                    "--release-commit",
                    f"{repo}={target_ref}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(extra.returncode, 0)
            self.assertIn("target tree does not match bound merge tree", extra.stderr)

    def test_release_binding_verifies_fast_forward_and_rejects_same_tree_squash(self) -> None:
        """同一 tree 的 squash 不能冒充从冻结 source branch 合入的 fast-forward。"""

        def prepare(directory: Path) -> tuple[Path, str, Path]:
            repo = directory / "repo"
            repo.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repo), *arguments], check=True)
            target_ref = subprocess.run(
                ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            source = repo / "service.go"
            source.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run(["git", "-C", str(repo), "switch", "-qc", "feature"], check=True)
            source.write_text("reviewed\n", encoding="utf-8")
            snapshot = directory / "snapshot.json"
            frozen = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--repo-target",
                    f"{repo}={target_ref}",
                    "--output",
                    str(snapshot),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            binding = directory / "binding.json"
            bound = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--bind-release-snapshot",
                    str(snapshot),
                    "--output",
                    str(binding),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "reviewed"], check=True)
            return repo, target_ref, binding

        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repo, target_ref, binding = prepare(directory)
            subprocess.run(
                ["git", "-C", str(repo), "switch", "-q", target_ref.removeprefix("refs/heads/")],
                check=True,
            )
            subprocess.run(["git", "-C", str(repo), "merge", "--ff-only", "feature"], check=True)
            fast_forward = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--verify-release-binding",
                    str(binding),
                    "--release-commit",
                    f"{repo}=HEAD",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(fast_forward.returncode, 0, fast_forward.stderr)

        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repo, target_ref, binding = prepare(directory)
            subprocess.run(
                ["git", "-C", str(repo), "switch", "-q", target_ref.removeprefix("refs/heads/")],
                check=True,
            )
            subprocess.run(["git", "-C", str(repo), "merge", "--squash", "feature"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "squashed"], check=True)
            squash = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--verify-release-binding",
                    str(binding),
                    "--release-commit",
                    f"{repo}=HEAD",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(squash.returncode, 0)
            self.assertIn("not the bound candidate", squash.stderr)

    def test_release_binding_accepts_already_committed_review_candidate(self) -> None:
        """B 路径：审查对象已经在 source commit 中，干净 index 也可直接绑定。"""
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repo = directory / "repo"
            repo.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repo), *arguments], check=True)
            target_ref = subprocess.run(
                ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            source = repo / "service.go"
            source.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run(["git", "-C", str(repo), "switch", "-qc", "feature"], check=True)
            source.write_text("already reviewed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "already reviewed"], check=True
            )

            snapshot = directory / "committed-review-snapshot.json"
            frozen = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--repo-target",
                    f"{repo}={target_ref}",
                    "--output",
                    str(snapshot),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            binding = directory / "committed-review-binding.json"
            bound = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--bind-release-snapshot",
                    str(snapshot),
                    "--output",
                    str(binding),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            subprocess.run(
                ["git", "-C", str(repo), "switch", "-q", target_ref.removeprefix("refs/heads/")],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "merge", "--no-ff", "feature", "-m", "merge committed review"],
                check=True,
            )
            verified = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--verify-release-binding",
                    str(binding),
                    "--release-commit",
                    f"{repo}=HEAD",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_release_binding_rejects_source_branch_advanced_after_binding(self) -> None:
        """A 路径 binding 后即使伪造旧 tree 的 merge，也不能跳过新增 source commit。"""
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            repo = directory / "repo"
            repo.mkdir()
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "skill-test@example.invalid"),
                ("config", "user.name", "Skill Test"),
            ):
                subprocess.run(["git", "-C", str(repo), *arguments], check=True)
            target_ref = subprocess.run(
                ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            source = repo / "service.go"
            source.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            target_revision = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(repo), "switch", "-qc", "feature"], check=True)
            source.write_text("reviewed A\n", encoding="utf-8")
            snapshot = directory / "working-review-snapshot.json"
            frozen = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--repo-target",
                    f"{repo}={target_ref}",
                    "--output",
                    str(snapshot),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            subprocess.run(["git", "-C", str(repo), "add", "service.go"], check=True)
            binding = directory / "working-review-binding.json"
            bound = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--bind-release-snapshot",
                    str(snapshot),
                    "--output",
                    str(binding),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            binding_payload = json.loads(binding.read_text(encoding="utf-8"))
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "reviewed A"], check=True)
            reviewed_commit = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (repo / "unreviewed.txt").write_text("B\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "unreviewed.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "unreviewed B"], check=True)

            # 模拟攻击者保留已审 A 的 merge tree / parents，却让 source ref 已指向 B。
            # 旧的 ancestor 判断会接受它；严格 HEAD 绑定必须拒绝。
            forged_merge = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "commit-tree",
                    binding_payload["repositories"][0]["merge_tree"],
                    "-p",
                    target_revision,
                    "-p",
                    reviewed_commit,
                ],
                input="forged merge\n",
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(repo), "update-ref", target_ref, forged_merge], check=True
            )
            rejected = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--verify-release-binding",
                    str(binding),
                    "--release-commit",
                    f"{repo}={target_ref}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("not the bound candidate", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
