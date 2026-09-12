"""Desktop UI for turning a creative brief into a MiniMax H3 prompt."""

from __future__ import annotations

import os
import json
from dataclasses import asdict
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from prompt_engine import (
    PromptSpec,
    build_structured_prompt,
    call_compatible_api,
    reference_tags_from_spec,
    split_shots,
    validate_prompt,
)
from skill_engine import (
    DEFAULT_SKILL,
    NONE_SPECIAL,
    build_ref2va_prompt,
    load_skill_profiles,
    profile_system_prompt,
)
from version_info import APP_VERSION
from workflow_engine import (
    WorkflowScan,
    compile_active_workflow,
    effective_reference_assets,
    load_workflow,
    remap_reference_value,
    stable_reference_id,
    timed_reference_rules,
)


APP_TITLE = f"H3 Prompt Studio v{APP_VERSION}"


class ScrolledFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0, background="#f4f1eb")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas, padding=(16, 14))
        window = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        self.body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))


class PromptStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1380x860")
        self.minsize(1050, 680)
        self.configure(background="#11151c")
        self.workflow_scan: WorkflowScan | None = None
        self.output_mapping_signature = ""
        self.skill_profiles = load_skill_profiles(Path.cwd())
        self.current_special_key: str | None = None
        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._load_example()
        self._auto_load_default_workflow()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f4f1eb")
        style.configure("TLabel", background="#f4f1eb", foreground="#20242c", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 19, "bold"), foreground="#f4f1eb", background="#11151c")
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 9), foreground="#98a2b3", background="#11151c")
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 11, "bold"), foreground="#b42318")
        style.configure("Muted.TLabel", font=("Microsoft YaHei UI", 9), foreground="#667085")
        style.configure("Warning.TLabel", font=("Microsoft YaHei UI", 9), foreground="#b54708")
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(12, 7))
        style.configure("Accent.TButton", background="#d92d20", foreground="white")
        style.map("Accent.TButton", background=[("active", "#b42318")])
        style.configure("TNotebook", background="#11151c", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 7), font=("Microsoft YaHei UI", 9))

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        self.skill_menu = tk.Menu(menu, tearoff=False)
        self.special_menu_var = tk.StringVar(value=NONE_SPECIAL)
        self._populate_skill_menu()
        menu.add_cascade(label="Skills", menu=self.skill_menu)
        self.config(menu=menu)

    def _populate_skill_menu(self) -> None:
        self.skill_menu.delete(0, "end")
        default = self.skill_profiles[DEFAULT_SKILL]
        self.skill_menu.add_command(
            label=f"✓ Default — {default.display_name} (always bound)", state="disabled"
        )
        specials = sorted(
            (profile for profile in self.skill_profiles.values() if profile.special),
            key=lambda profile: profile.display_name.casefold(),
        )
        self.skill_menu.add_separator()
        self.skill_menu.add_command(label="Special Skills", state="disabled")
        self.skill_menu.add_radiobutton(
            label="None — no special scenario",
            variable=self.special_menu_var,
            value=NONE_SPECIAL,
            command=lambda: self._select_special(None),
        )
        for profile in specials:
            key = profile.key
            self.skill_menu.add_radiobutton(
                label=f"{profile.display_name}  [{profile.key}]",
                variable=self.special_menu_var,
                value=key,
                command=lambda selected=key: self._select_special(selected),
            )
        self.skill_menu.add_separator()
        self.skill_menu.add_command(label="Rescan Skill folders", command=self._rescan_skills)
        self.skill_menu.add_command(label="View current Skill source…", command=self._show_current_skill)

    def _default_profile(self):
        return self.skill_profiles[DEFAULT_SKILL]

    def _special_profile(self):
        if self.current_special_key is None:
            return None
        return self.skill_profiles.get(self.current_special_key)

    def _skill_binding_summary(self) -> str:
        default = self.skill_profiles[DEFAULT_SKILL]
        special = self._special_profile()
        if special is not None and special.standalone:
            return f"Binding: Standalone Special {special.display_name}"
        special_name = special.display_name if special else "None"
        return f"Binding: Default {default.display_name} + Special {special_name}"

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Dark.TFrame", padding=(18, 14))
        ttk.Style(self).configure("Dark.TFrame", background="#11151c")
        header.pack(fill="x")
        title_box = ttk.Frame(header, style="Dark.TFrame")
        title_box.pack(side="left")
        ttk.Label(title_box, text="H3 PROMPT STUDIO", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Turn a creative brief into a clear, continuous, checkable Reference-to-Video shot prompt", style="Sub.TLabel").pack(anchor="w")
        self.profile_var = tk.StringVar(value=self._skill_binding_summary())
        ttk.Label(title_box, textvariable=self.profile_var, style="Sub.TLabel").pack(anchor="w", pady=(3, 0))

        actions = ttk.Frame(header, style="Dark.TFrame")
        actions.pack(side="right")
        ttk.Button(actions, text="Build offline", style="Accent.TButton", command=self._generate_offline).pack(side="left", padx=4)
        ttk.Button(actions, text="AI English polish", command=self._generate_ai).pack(side="left", padx=4)
        ttk.Button(actions, text="Copy result", command=self._copy_output).pack(side="left", padx=4)
        ttk.Button(actions, text="Save…", command=self._save_output).pack(side="left", padx=4)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        form_scroll = ScrolledFrame(paned)
        output_panel = ttk.Frame(paned, padding=(12, 10))
        paned.add(form_scroll, weight=5)
        paned.add(output_panel, weight=6)
        self._build_form(form_scroll.body)
        self._build_output(output_panel)

    def _text_field(self, parent: ttk.Frame, label: str, height: int, hint: str = "") -> tk.Text:
        ttk.Label(parent, text=label, style="Section.TLabel").pack(anchor="w", pady=(11, 4))
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(0, 4))
        widget = tk.Text(parent, height=height, wrap="word", undo=True, font=("Microsoft YaHei UI", 10), relief="solid", borderwidth=1)
        widget.pack(fill="x")
        return widget

    def _build_form(self, parent: ttk.Frame) -> None:
        self._build_workflow_section(parent)
        ttk.Separator(parent).pack(fill="x", pady=16)
        ttk.Label(parent, text="01  Concept & visuals", style="Section.TLabel").pack(anchor="w")
        self.brief = self._text_field(parent, "Story brief *", 4, "Describe the characters, goal, setting and dramatic progression; Chinese or English both work.")
        self.style = self._text_field(parent, "Global visual style", 3, "Style, linework, palette, lighting, location and time of day.")
        self.references = self._text_field(parent, "References & consistency", 3, "State which character, object or shot each <Picture N> corresponds to.")
        self.audio = self._text_field(parent, "Audio rules", 2, "e.g. Use <Audio 1> exactly as supplied; preserve timing and dialogue.")

        ttk.Separator(parent).pack(fill="x", pady=16)
        ttk.Label(parent, text="02  Shot timeline", style="Section.TLabel").pack(anchor="w")
        self.shots = self._text_field(parent, "Shot plan *", 7, "One shot per line, in time order. Include camera position, subject action, camera movement and environment response.")
        self.dialogue = self._text_field(parent, "Dialogue / on-screen text (kept exactly)", 4, "Format: shot number|text, e.g. 1|GET READY TO MEET YOUR MAKER")
        self.transition = self._text_field(parent, "Transitions between shots", 2, "The same transition is inserted between every pair of shots; AI mode can redesign it to suit the content.")
        self.ending = self._text_field(parent, "Ending hold", 2, "State what final image is held, until when, and whether extra shots are forbidden.")

        ttk.Separator(parent).pack(fill="x", pady=16)
        ttk.Label(parent, text="03  Constraints & output", style="Section.TLabel").pack(anchor="w")
        self.must_keep = self._text_field(parent, "Must keep / avoid", 3, "Identity, costume, props, proportions, spelling, and anything that must not be added.")
        self.technical = self._text_field(parent, "Technical specs", 2, "Duration, aspect ratio, frame rate or shot timings; leave empty if unsure.")

        settings = ttk.LabelFrame(parent, text="Optional: OpenAI-compatible AI endpoint", padding=10)
        settings.pack(fill="x", pady=(16, 8))
        self.endpoint_var = tk.StringVar(value=os.getenv("H3_API_ENDPOINT", ""))
        self.model_var = tk.StringVar(value=os.getenv("H3_API_MODEL", ""))
        self.key_var = tk.StringVar(value=os.getenv("H3_API_KEY", ""))
        for label, variable, secret in (
            ("Full endpoint", self.endpoint_var, False),
            ("Model name", self.model_var, False),
            ("API key (not saved)", self.key_var, True),
        ):
            ttk.Label(settings, text=label).pack(anchor="w", pady=(5, 2))
            ttk.Entry(settings, textvariable=variable, show="•" if secret else "").pack(fill="x")
        ttk.Label(
            settings,
            text="Endpoints ending in /responses use the Responses API; any other URL is called in chat/completions format.",
            style="Muted.TLabel",
            wraplength=500,
        ).pack(anchor="w", pady=(8, 0))

    def _build_workflow_section(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="00  ComfyUI workflow & asset nodes", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="After loading an API-format JSON, Picture, Video and Audio mappings are built automatically from the node connections.",
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor="w", pady=(3, 6))

        path_row = ttk.Frame(parent)
        path_row.pack(fill="x")
        self.workflow_path_var = tk.StringVar()
        ttk.Entry(path_row, textvariable=self.workflow_path_var, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(path_row, text="Load API…", command=self._choose_workflow).pack(side="left", padx=(6, 0))
        ttk.Button(path_row, text="Rescan", command=self._reload_workflow).pack(side="left", padx=(6, 0))

        columns = ("tag", "kind", "node", "range", "state", "filename")
        self.asset_tree = ttk.Treeview(parent, columns=columns, show="headings", height=8)
        headings = {
            "tag": "H3 tag",
            "kind": "Type",
            "node": "Node",
            "range": "Asset time range",
            "state": "Current window",
            "filename": "Asset file",
        }
        widths = {"tag": 95, "kind": 75, "node": 55, "range": 105, "state": 65, "filename": 210}
        for name in columns:
            self.asset_tree.heading(name, text=headings[name])
            self.asset_tree.column(name, width=widths[name], minwidth=55, stretch=name == "filename")
        self.asset_tree.pack(fill="x", pady=(8, 4))
        self.asset_tree.bind("<<TreeviewSelect>>", self._on_asset_select)

        clip_box = ttk.LabelFrame(parent, text="Current generation clip window", padding=8)
        clip_box.pack(fill="x", pady=(7, 3))
        self.clip_start_var = tk.StringVar(value="0.00")
        self.clip_end_var = tk.StringVar(value="5.00")
        ttk.Label(clip_box, text="Start (s)").pack(side="left")
        ttk.Entry(clip_box, textvariable=self.clip_start_var, width=8).pack(side="left", padx=(4, 10))
        ttk.Label(clip_box, text="End (s)").pack(side="left")
        ttk.Entry(clip_box, textvariable=self.clip_end_var, width=8).pack(side="left", padx=(4, 10))
        ttk.Button(clip_box, text="Apply window", command=self._apply_clip_window).pack(side="left")
        ttk.Button(clip_box, text="Export active API…", command=self._export_active_workflow).pack(side="right")

        asset_box = ttk.LabelFrame(parent, text="Selected asset's active range", padding=8)
        asset_box.pack(fill="x", pady=(3, 6))
        self.asset_start_var = tk.StringVar(value="0.00")
        self.asset_end_var = tk.StringVar(value="5.00")
        self.asset_enabled_var = tk.BooleanVar(value=True)
        ttk.Label(asset_box, text="Start (s)").pack(side="left")
        ttk.Entry(asset_box, textvariable=self.asset_start_var, width=8).pack(side="left", padx=(4, 10))
        ttk.Label(asset_box, text="End (s)").pack(side="left")
        ttk.Entry(asset_box, textvariable=self.asset_end_var, width=8).pack(side="left", padx=(4, 10))
        ttk.Checkbutton(asset_box, text="Allow activation", variable=self.asset_enabled_var).pack(side="left")
        ttk.Button(asset_box, text="Apply to asset", command=self._apply_asset_range).pack(side="right")
        self.workflow_summary_var = tk.StringVar(value="No workflow loaded yet")
        self.workflow_warning_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.workflow_summary_var, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            textvariable=self.workflow_warning_var,
            style="Warning.TLabel",
            wraplength=520,
        ).pack(anchor="w", pady=(2, 0))

    def _build_output(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True)
        prompt_tab = ttk.Frame(notebook, padding=8)
        check_tab = ttk.Frame(notebook, padding=8)
        notebook.add(prompt_tab, text="Result")
        notebook.add(check_tab, text="Structure check")
        self.output = tk.Text(
            prompt_tab,
            wrap="word",
            undo=True,
            font=("Consolas", 10),
            background="#151a22",
            foreground="#edf2f7",
            insertbackground="white",
            selectbackground="#b42318",
            padx=14,
            pady=12,
            relief="flat",
        )
        out_scroll = ttk.Scrollbar(prompt_tab, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=out_scroll.set)
        self.output.pack(side="left", fill="both", expand=True)
        out_scroll.pack(side="right", fill="y")
        self.check = tk.Text(check_tab, wrap="word", font=("Microsoft YaHei UI", 11), padx=16, pady=14, relief="flat")
        self.check.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(parent, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

    def _choose_workflow(self) -> None:
        filename = filedialog.askopenfilename(
            title="Load ComfyUI API workflow",
            filetypes=[("ComfyUI workflow", "*.json"), ("All files", "*.*")],
            initialdir=str(Path.cwd()),
        )
        if filename:
            self._load_workflow_path(Path(filename), show_error=True)

    def _reload_workflow(self) -> None:
        value = self.workflow_path_var.get().strip()
        if value:
            self._load_workflow_path(Path(value), show_error=True)
        else:
            self._choose_workflow()

    def _auto_load_default_workflow(self) -> None:
        preferred = Path.cwd() / "video_minimax_h3_r2v_9image_3audio_3video_api.json"
        if preferred.exists():
            self._load_workflow_path(preferred, show_error=False)

    def _load_workflow_path(self, path: Path, show_error: bool) -> None:
        try:
            scan = load_workflow(path)
        except (OSError, ValueError) as exc:
            self.status_var.set("Workflow failed to load")
            if show_error:
                messagebox.showerror(APP_TITLE, str(exc))
            return

        self.workflow_scan = scan
        self.workflow_path_var.set(str(scan.path))
        self.clip_start_var.set("0.00")
        self.clip_end_var.set(f"{scan.duration_seconds:.2f}")
        self.asset_start_var.set("0.00")
        self.asset_end_var.set(f"{scan.duration_seconds:.2f}")
        self._refresh_asset_tree()
        counts = scan.counts
        paired = sum(bool(asset.paired_audio_binding) for asset in scan.assets if asset.media_type == "video")
        self.workflow_summary_var.set(
            f"{len(scan.nodes)} nodes found · H3 nodes {len(scan.h3_node_ids)} · "
            f"images {counts['image']}/9 · videos {counts['video']}/3 (paired audio {paired}) · "
            f"standalone audio {counts['audio']}/3 · project {scan.duration_seconds:.2f}s"
        )
        self.workflow_warning_var.set("\n".join(f"! {warning}" for warning in scan.warnings))
        self._sync_reference_fields()
        self.status_var.set(f"Loaded workflow: {path.name}; auto-mapped {len(scan.assets)} asset nodes")

    def _clip_window(self) -> tuple[float, float]:
        if not self.workflow_scan:
            raise ValueError("Load a workflow first.")
        try:
            start = float(self.clip_start_var.get())
            end = float(self.clip_end_var.get())
        except ValueError as exc:
            raise ValueError("The window must be numeric.") from exc
        if start < 0 or end <= start or end > self.workflow_scan.duration_seconds:
            raise ValueError(
                f"The window must satisfy 0 ≤ start < end ≤ {self.workflow_scan.duration_seconds:.2f}s。"
            )
        return start, end

    def _refresh_asset_tree(self) -> None:
        if not self.workflow_scan:
            return
        selected = self.asset_tree.selection()
        selected_node = selected[0] if selected else ""
        kind_names = {"image": "Image", "video": "Video + paired audio", "audio": "Standalone audio"}
        try:
            clip_start, clip_end = self._clip_window()
        except ValueError:
            clip_start, clip_end = 0.0, self.workflow_scan.duration_seconds
        for row in self.asset_tree.get_children():
            self.asset_tree.delete(row)
        for asset in self.workflow_scan.assets:
            relevant = asset.overlaps(clip_start, clip_end)
            state = "Active" if relevant else ("Disabled" if not asset.enabled else "Outside window")
            self.asset_tree.insert(
                "",
                "end",
                iid=asset.node_id,
                values=(
                    asset.tag,
                    kind_names.get(asset.media_type, asset.media_type),
                    asset.node_id,
                    f"{asset.start_seconds:.2f}–{asset.end_seconds:.2f}s",
                    state,
                    asset.filename or "(no file set)",
                ),
            )
        if selected_node and self.asset_tree.exists(selected_node):
            self.asset_tree.selection_set(selected_node)

    def _selected_asset(self):
        if not self.workflow_scan or not self.asset_tree.selection():
            return None
        node_id = self.asset_tree.selection()[0]
        return next((asset for asset in self.workflow_scan.assets if asset.node_id == node_id), None)

    def _on_asset_select(self, _event=None) -> None:
        asset = self._selected_asset()
        if not asset:
            return
        self.asset_start_var.set(f"{asset.start_seconds:.2f}")
        self.asset_end_var.set(f"{asset.end_seconds:.2f}")
        self.asset_enabled_var.set(asset.enabled)

    def _apply_asset_range(self) -> None:
        asset = self._selected_asset()
        if not asset or not self.workflow_scan:
            messagebox.showinfo(APP_TITLE, "Select a node in the asset list first.")
            return
        try:
            start = float(self.asset_start_var.get())
            end = float(self.asset_end_var.get())
            if start < 0 or end <= start or end > self.workflow_scan.duration_seconds:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                APP_TITLE,
                f"The asset range must satisfy 0 ≤ start < end ≤ {self.workflow_scan.duration_seconds:.2f}s。",
            )
            return
        asset.start_seconds = start
        asset.end_seconds = end
        asset.enabled = self.asset_enabled_var.get()
        self._refresh_asset_tree()
        self._sync_reference_fields()
        self.status_var.set(f"{asset.tag} range updated to {start:.2f}–{end:.2f}s")

    def _apply_clip_window(self) -> None:
        try:
            start, end = self._clip_window()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self._refresh_asset_tree()
        self._sync_reference_fields()
        active_count = len(self.workflow_scan.active_assets(start, end)) if self.workflow_scan else 0
        self.status_var.set(f"Current generation clip: {start:.2f}–{end:.2f}s; {active_count} assets active")

    def _sync_reference_fields(self) -> None:
        if not self.workflow_scan:
            return
        try:
            start, end = self._clip_window()
        except ValueError:
            start, end = 0.0, self.workflow_scan.duration_seconds
        visual_rules, audio_rules = timed_reference_rules(self.workflow_scan.active_assets(start, end))
        self._replace(self.references, visual_rules)
        self._replace(self.audio, audio_rules or "N/A")

    def _export_active_workflow(self) -> None:
        if not self.workflow_scan:
            messagebox.showinfo(APP_TITLE, "Load a workflow first.")
            return
        try:
            start, end = self._clip_window()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        default_profile = self._default_profile()
        special_profile = self._special_profile()
        active = self.workflow_scan.active_assets(start, end)
        prompt_assets, _ = effective_reference_assets(active)
        existing_prompt = self._get(self.output)
        prompt = (
            existing_prompt
            if existing_prompt
            and self.output_mapping_signature == self._reference_mapping_signature()
            else build_ref2va_prompt(
                self._spec(), prompt_assets, end - start, default_profile,
                special_profile, source_assets=self.workflow_scan.assets,
            )
        )
        compiled, active = compile_active_workflow(self.workflow_scan, start, end, prompt=prompt)
        filename = filedialog.asksaveasfilename(
            title="Export the active ComfyUI API for the current window",
            initialfile=f"active_{start:.2f}-{end:.2f}s_api.json",
            defaultextension=".json",
            filetypes=[("ComfyUI API", "*.json")],
        )
        if not filename:
            return
        Path(filename).write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status_var.set(f"Exported active API: {len(active)} assets · {end-start:.2f}s")

    def _select_special(self, key: str | None) -> None:
        # Re-read the files on every menu click so edits in the local Skill
        # folder take effect without restarting the application.
        self.skill_profiles = load_skill_profiles(Path.cwd())
        if key is not None and (key not in self.skill_profiles or not self.skill_profiles[key].special):
            key = None
        self.current_special_key = key
        self.special_menu_var.set(key or NONE_SPECIAL)
        self._populate_skill_menu()
        self.profile_var.set(self._skill_binding_summary())
        self.status_var.set(f"Skill binding updated: {self._skill_binding_summary().removeprefix('Binding: ')}")

    def _rescan_skills(self) -> None:
        try:
            self.skill_profiles = load_skill_profiles(Path.cwd())
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, f"Skill scan failed: {exc}")
            return
        if self.current_special_key not in self.skill_profiles:
            self.current_special_key = None
            self.special_menu_var.set(NONE_SPECIAL)
        self._populate_skill_menu()
        self.profile_var.set(self._skill_binding_summary())
        special_count = sum(item.special for item in self.skill_profiles.values())
        self.status_var.set(f"Skill folders rescanned: 1 Default, {special_count} Special")

    def _show_current_skill(self) -> None:
        self.skill_profiles = load_skill_profiles(Path.cwd())
        default = self._default_profile()
        special = self._special_profile()
        window = tk.Toplevel(self)
        window.title(self._skill_binding_summary())
        window.geometry("960x720")
        text_widget = tk.Text(window, wrap="word", font=("Consolas", 10), padx=12, pady=12)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        if special is not None and special.standalone:
            content = (
                f"=== STANDALONE SPECIAL · {special.display_name} [{special.key}] ===\n\n"
                + special.instruction
                + "\n\nDefault h3-prompt-writing is not bound in this mode."
            )
        else:
            content = (
                f"=== DEFAULT · BOUND · {default.display_name} ===\n\n"
                + default.instruction
                + "\n\n--- DEFAULT Ref2VA required guide ---\n\n"
                + default.h3_reference_guide
            )
        if special is not None and not special.standalone:
            content += (
                f"\n\n=== SPECIAL · {special.display_name} [{special.key}] ===\n\n"
                + special.instruction
            )
        elif special is None:
            content += "\n\n=== SPECIAL ===\n\nNone — no scene-specific skill is bound."
        text_widget.insert("1.0", content)
        text_widget.configure(state="disabled")

    @staticmethod
    def _get(widget: tk.Text) -> str:
        return widget.get("1.0", "end-1c").strip()

    def _spec(self) -> PromptSpec:
        return PromptSpec(
            brief=self._get(self.brief),
            style=self._get(self.style),
            references=self._get(self.references),
            audio=self._get(self.audio),
            shots=split_shots(self._get(self.shots)),
            dialogue=self._get(self.dialogue),
            transition=self._get(self.transition),
            ending=self._get(self.ending),
            must_keep=self._get(self.must_keep),
            technical=self._get(self.technical),
        )

    def _input_ok(self, spec: PromptSpec) -> bool:
        if not spec.brief or not spec.shots:
            messagebox.showwarning(APP_TITLE, "Fill in at least the “Story brief” and one line of “Shot plan”.")
            return False
        return True

    def _reference_mapping_signature(self) -> str:
        if not self.workflow_scan:
            return ""
        try:
            start, end = self._clip_window()
        except ValueError:
            return ""
        active = self.workflow_scan.active_assets(start, end)
        effective, _ = effective_reference_assets(active)
        rows = sorted(
            (
                stable_reference_id(asset),
                asset.tag,
                asset.source_node_id or asset.node_id,
                asset.binding,
            )
            for asset in effective
        )
        return json.dumps([start, end, rows], ensure_ascii=False)

    def _set_output(
        self,
        text: str,
        spec: PromptSpec,
        mapping_signature: str | None = None,
    ) -> None:
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text.strip())
        self.output_mapping_signature = (
            self._reference_mapping_signature()
            if mapping_signature is None
            else mapping_signature
        )
        report = validate_prompt(text, reference_tags_from_spec(spec))
        self.check.delete("1.0", "end")
        self.check.insert("1.0", report.as_text())
        self.status_var.set(f"Done · {len(text):,} characters · structure score {report.score}/100")

    def _generate_offline(self) -> None:
        spec = self._spec()
        if not self._input_ok(spec):
            return
        default_profile = self._default_profile()
        special_profile = self._special_profile()
        if self.workflow_scan:
            try:
                start, end = self._clip_window()
            except ValueError as exc:
                messagebox.showerror(APP_TITLE, str(exc))
                return
            active_assets = self.workflow_scan.active_assets(start, end)
            assets, _ = effective_reference_assets(active_assets)
            source_assets = self.workflow_scan.assets
            validation_spec = PromptSpec(
                **remap_reference_value(asdict(spec), source_assets, assets)
            )
            duration = end - start
        else:
            assets, source_assets, validation_spec, duration = [], None, spec, 5.0
        self._set_output(
            build_ref2va_prompt(
                spec, assets, duration, default_profile, special_profile,
                source_assets=source_assets,
            ),
            validation_spec,
        )

    def _generate_ai(self) -> None:
        spec = self._spec()
        if not self._input_ok(spec):
            return
        endpoint = self.endpoint_var.get().strip()
        model = self.model_var.get().strip()
        api_key = self.key_var.get()
        default_profile = self._default_profile()
        special_profile = self._special_profile()
        api_spec = spec
        mapping_signature = self._reference_mapping_signature()
        if self.workflow_scan:
            try:
                start, end = self._clip_window()
            except ValueError as exc:
                messagebox.showerror(APP_TITLE, str(exc))
                return
            active = self.workflow_scan.active_assets(start, end)
            effective, _ = effective_reference_assets(active)
            api_spec = PromptSpec(
                **remap_reference_value(
                    asdict(spec),
                    self.workflow_scan.assets,
                    effective,
                )
            )
        if not endpoint or not model:
            messagebox.showwarning(APP_TITLE, "AI English polish needs a full endpoint and a model name.")
            return
        self.status_var.set("AI is rewriting, please wait…")

        def work() -> None:
            try:
                text = call_compatible_api(
                    endpoint,
                    api_key,
                    model,
                    api_spec,
                    system_prompt=profile_system_prompt(default_profile, special_profile),
                )
            except Exception as exc:  # Surface network/provider errors in the UI.
                self.after(0, lambda: self._show_ai_error(str(exc)))
                return
            self.after(
                0,
                lambda: self._set_output(text, api_spec, mapping_signature),
            )

        threading.Thread(target=work, daemon=True).start()

    def _show_ai_error(self, detail: str) -> None:
        self.status_var.set("AI request failed; offline build is still available")
        messagebox.showerror(APP_TITLE, detail)

    def _copy_output(self) -> None:
        text = self._get(self.output)
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Copied to clipboard")

    def _save_output(self) -> None:
        text = self._get(self.output)
        if not text:
            messagebox.showinfo(APP_TITLE, "There is no result to save yet.")
            return
        filename = filedialog.asksaveasfilename(
            title="Save H3 prompt",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("Markdown", "*.md"), ("All files", "*.*")],
        )
        if filename:
            Path(filename).write_text(text, encoding="utf-8")
            self.status_var.set(f"Saved: {filename}")

    @staticmethod
    def _replace(widget: tk.Text, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _load_example(self) -> None:
        self._replace(self.brief, "On a rooftop in a city at night, a confident young boy hero taunts a giant mechanical monster; the monster answers with a roar that shakes the whole city.")
        self._replace(self.style, "Bold comic-book ink style, heavy linework, red and blue-black palette, night city.")
        self._replace(self.references, "Use <Picture 1> only for the boy's identity and costume in CUT 1. Use <Picture 2> only for the mech-kaiju design and scale in CUT 2. Maintain exact visual identity.")
        self._replace(self.audio, "Use <Audio 1> exactly as supplied. Do not replace, trim, retime, or add dialogue.")
        self._replace(self.shots, "Top-down rooftop view of the boy superhero; his red cape flutters, hands on hips, and the camera slowly descends as he looks into the lens.\nLow hero angle on the colossal black mech-kaiju above the skyline; it rears back, roars, and leans toward the camera as the city reacts to the shockwave.")
        self._replace(self.dialogue, "1|GET READY TO\n1|MEET\n1|YOUR\n1|MAKER")
        self._replace(self.transition, "A violent whip pan smears the floating comic words away and resolves into the upward motion of the next low-angle shot.")
        self._replace(self.ending, "Hold the final close low-angle shot for the remainder of <Audio 1> while the mech-kaiju continues roaring. Do not cut away.")
        self._replace(self.must_keep, "Keep all four text blocks spelled exactly; do not merge or omit words. No extra characters, captions, music, or shots.")
        self._replace(self.technical, "Short-form video; preserve chronological audio synchronization and consistent night lighting.")


if __name__ == "__main__":
    PromptStudio().mainloop()
