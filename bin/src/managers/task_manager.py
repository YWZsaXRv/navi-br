import logging
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Set, List

# QObject and pyqtSlot for robust threading
from PyQt6.QtCore import QTimer, QMetaObject, Qt, QObject, pyqtSlot
from PyQt6.QtWidgets import QFileDialog, QMessageBox

try:
    import psutil
except ImportError:
    psutil = None

from core import steam_helpers
from core.tasks.download_depots_task import DownloadDepotsTask
from core.tasks.download_slssteam_task import DownloadSLSsteamTask
from core.tasks.generate_achievements_task import GenerateAchievementsTask
from core.tasks.monitor_speed_task import SpeedMonitorTask
from core.tasks.process_zip_task import ProcessZipTask
from core.tasks.steamless_task import SteamlessTask

from utils.helpers import get_base_path
from utils.steam_manifest import get_game_directory, write_acf_file
from utils.wrapper_metadata import persist_selected_dlcs
from utils.yaml_config_manager import (
    is_slssteam_mode_enabled,
    is_slssteam_config_management_enabled,
)

from utils.paths import Paths
from utils.task_runner import TaskRunner

logger = logging.getLogger(__name__)


class TaskManager(QObject):
    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings

        # Task state
        self.speed_monitor_task = None
        self.speed_monitor_runner = None
        self.is_awaiting_speed_monitor_stop = False

        self.zip_task = None
        self.zip_task_runner = None
        self.is_awaiting_zip_task_stop = False

        self.download_task = None
        self.download_runner = None
        self.is_awaiting_download_stop = False
        self.achievement_task = None
        self.achievement_task_runner = None
        self.achievement_worker = None
        self.steamless_task = None
        self.slssteam_download_task = None
        self.slssteam_download_runner = None

        # Processing state
        self.is_processing = False
        self.is_download_paused = False
        self.is_cancelling = False
        self.current_job: Optional[str] = None
        self.current_job_metadata: Optional[Dict[str, Any]] = None
        self.game_data: Optional[Dict[str, Any]] = None
        self.current_dest_path: Optional[str] = None
        self.slssteam_mode_was_active = False
        self.library_mode_was_active = False
        self._steamless_success = None
        self._steamless_manual_run = False

        # Job step states
        self._job_steps_completed: Set[str] = set()

        # Progress tracking
        self._steamless_progress_log = []
        self._steamless_game_name = ""

        # Status tracking
        self._last_steamless_success = None
        self._steamless_ran = False
        self._steamless_error = False
        self._slscheevo_ran = False
        self._slscheevo_error = False

        self._last_ddm_status = "not_run"
        self._last_ddm_status_text = "N/A"
        self._last_slscheevo_status = "not_run"
        self._last_slscheevo_status_text = "N/A"
        self._last_steamless_status = "not_run"
        self._last_steamless_status_text = "N/A"
        self._last_installed_game = None

        self._delete_files_on_cancel: Optional[bool] = None

        # Status colors
        self.STATUS_OK = "#00FF00"
        self.STATUS_IN_PROGRESS = "#FFA500"
        self.STATUS_ERROR = "#FF0000"

    @property
    def last_installed_game(self):
        return self._last_installed_game

    def start_zip_processing(self, zip_path, metadata=None):
        self.is_processing = True
        self.current_job = zip_path
        self.current_job_metadata = metadata or {}
        self._job_steps_completed.clear()

        if self.main_window:
            self.main_window.progress_bar.setVisible(True)
            self.main_window.progress_bar.setRange(0, 0)
            self.main_window.drop_text_label.setText(
                f"Processing: {os.path.basename(zip_path)}"
            )

        self.zip_task = ProcessZipTask()
        self.zip_task_runner = TaskRunner()
        self.is_awaiting_zip_task_stop = True
        self.zip_task_runner.cleanup_complete.connect(self._on_zip_task_stopped)

        worker = self.zip_task_runner.run(self.zip_task.run, zip_path)
        worker.finished.connect(self._on_zip_processed)
        worker.error.connect(self._handle_task_error)

    def _on_zip_processed(self, game_data):
        self.main_window.progress_bar.setRange(0, 100)
        self.main_window.progress_bar.setValue(100)
        self.game_data = game_data

        if self.game_data and self.game_data.get("depots"):
            self._show_depot_selection_dialog()
        else:
            QMessageBox.warning(
                self.main_window,
                "No Depots Found",
                "Zip file processed, but no downloadable depots were found.",
            )
            self.job_finished()

    def _show_depot_selection_dialog(self):
        # Deferred import to prevent circular dependency
        from ui.dialogs.depotselection import DepotSelectionDialog

        game_data = self.game_data
        if not game_data:
            self.job_finished()
            return

        auto_skip_single_choice = self.settings.value(
            "auto_skip_single_choice", False, type=bool
        )
        depots = game_data.get("depots") or {}
        if auto_skip_single_choice and len(depots) == 1:
            selected_depots = list(depots.keys())
            if self.game_data:
                self.game_data["selected_depots_list"] = selected_depots
            self._start_download_with_destination(selected_depots)
            return

        self.main_window.ui_state.depot_dialog = DepotSelectionDialog(
            game_data["appid"],
            game_data["game_name"],
            game_data["depots"],
            self.main_window,
        )

        if self.main_window.ui_state.depot_dialog.exec():
            selected_depots = (
                self.main_window.ui_state.depot_dialog.get_selected_depots()
            )
            if self.game_data:
                self.game_data["selected_depots_list"] = selected_depots

            if not selected_depots:
                self.job_finished()
                return

            self._start_download_with_destination(selected_depots)
        else:
            self.job_finished()

    def _start_download_with_destination(self, selected_depots):
        dest_path = self._get_destination_path()
        if dest_path:
            self._start_download(selected_depots, dest_path)
        else:
            self.job_finished()

    def _get_destination_path(self):
        slssteam_mode = is_slssteam_mode_enabled()
        library_mode = self.settings.value("library_mode", False, type=bool)
        current_job_metadata = self.current_job_metadata or {}
        existing_library_path = current_job_metadata.get("library_path")

        if slssteam_mode:
            self._handle_slssteam_mode()
            if existing_library_path:
                return existing_library_path
            return self._get_library_destination_path()
        elif library_mode:
            if existing_library_path:
                return existing_library_path
            return self._get_library_destination_path()
        else:
            return QFileDialog.getExistingDirectory(
                self.main_window, "Select Destination Folder"
            )

    def _get_library_destination_path(self):
        # Deferred import
        from ui.dialogs.steamlibrary import SteamLibraryDialog

        libraries = steam_helpers.get_steam_libraries()
        if libraries:
            auto_skip_single_choice = self.settings.value(
                "auto_skip_single_choice", False, type=bool
            )
            if auto_skip_single_choice and len(libraries) == 1:
                return libraries[0]
            dialog = SteamLibraryDialog(libraries, self.main_window)
            if dialog.exec():
                return dialog.get_selected_path()
            else:
                return None
        else:
            return QFileDialog.getExistingDirectory(
                self.main_window, "Select Destination Folder"
            )

    def _handle_slssteam_mode(self):
        # Deferred import
        from ui.dialogs.dlcselection import DlcSelectionDialog

        game_data = self.game_data
        if not game_data:
            return

        if sys.platform == "win32" and game_data.get("dlcs"):
            dlc_dialog = DlcSelectionDialog(game_data["dlcs"], self.main_window)
            if dlc_dialog.exec():
                game_data["selected_dlcs"] = dlc_dialog.get_selected_dlcs()

    def _start_download(self, selected_depots, dest_path):
        if not self.game_data:
            self.job_finished()
            return

        # Reset step tracker for this new download phase
        self._job_steps_completed.clear()

        self.current_dest_path = dest_path
        self.slssteam_mode_was_active = is_slssteam_mode_enabled()
        self.library_mode_was_active = self.settings.value(
            "library_mode", False, type=bool
        )
        self.is_cancelling = False

        self._last_steamless_success = None
        self._steamless_ran = False
        self._steamless_error = False
        self._slscheevo_ran = False
        self._slscheevo_error = False
        self._last_ddm_status = "in_progress"
        self._last_ddm_status_text = "Downloading..."
        self._last_slscheevo_status = "not_run"
        self._last_slscheevo_status_text = "N/A"
        self._last_steamless_status = "not_run"
        self._last_steamless_status_text = "N/A"

        self.main_window.ui_state.switch_to_download_gif()
        self._update_status_button_color()
        self.main_window.drop_text_label.setText(
            f"Downloading: {self.game_data.get('game_name', '')}"
        )

        self.main_window.progress_bar.setVisible(True)
        self.main_window.progress_bar.setValue(0)
        self.main_window.speed_label.setVisible(True)

        self.download_task = DownloadDepotsTask()
        self.download_task.progress.connect(logger.info)
        self.download_task.progress_percentage.connect(
            self.main_window.progress_bar.setValue
        )
        self.download_task.completed.connect(self._on_download_complete)
        self.download_task.error.connect(self._handle_task_error)

        self.download_runner = TaskRunner()
        self.is_awaiting_download_stop = True
        self.download_runner.cleanup_complete.connect(self._on_download_task_stopped)
        worker = self.download_runner.run(
            self.download_task.run, self.game_data, selected_depots, dest_path
        )
        worker.error.connect(self._handle_task_error)

        self._start_speed_monitor()
        self.is_download_paused = False
        self.main_window.ui_state.pause_button.setText("Pause")
        self.main_window.ui_state.pause_button.setVisible(True)
        self.main_window.ui_state.cancel_button.setVisible(True)

        if not self.slssteam_mode_was_active:
            app_token = self.game_data.get("app_token")
            if app_token:
                game_dir = get_game_directory(dest_path, self.game_data)
                token_file = os.path.join(game_dir, "apptoken.txt")
                try:
                    os.makedirs(game_dir, exist_ok=True)
                    with open(token_file, "w") as f:
                        f.write(app_token)
                except OSError as e:
                    logger.error(f"Failed to write app token: {e}")

    def _start_speed_monitor(self):
        self.speed_monitor_task = SpeedMonitorTask()
        self.speed_monitor_task.speed_update.connect(
            self.main_window.speed_label.setText
        )

        self.speed_monitor_runner = TaskRunner()
        self.speed_monitor_runner.cleanup_complete.connect(
            self._on_speed_monitor_stopped
        )
        self.speed_monitor_runner.run(self.speed_monitor_task.run)

    def _stop_speed_monitor(self):
        if self.speed_monitor_task:
            self.speed_monitor_task.stop()
            self.speed_monitor_task = None
        else:
            if self.is_awaiting_speed_monitor_stop:
                self.is_awaiting_speed_monitor_stop = False
                self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_speed_monitor_stopped(self):
        self.speed_monitor_runner = None
        self.is_awaiting_speed_monitor_stop = False
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_zip_task_stopped(self):
        self.zip_task_runner = None
        self.is_awaiting_zip_task_stop = False
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_download_task_stopped(self):
        self.download_runner = None
        self.is_awaiting_download_stop = False
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_download_complete(self):
        """Handle download completion"""
        if self.is_cancelling:
            if self._delete_files_on_cancel:
                self._cleanup_cancelled_job_files()
            self.job_finished()
            return

        self._stop_speed_monitor()
        self.main_window.progress_bar.setValue(100)

        if not self.game_data:
            if self.is_processing:
                self.job_finished()
            return

        self.main_window.drop_text_label.setText("Finalizando instalação...")
        logger.info("Starting post-download I/O processing in background thread...")

        size_on_disk = 0
        if self.download_task:
            size_on_disk = self.download_task.total_download_size_for_this_job

        config_management_enabled_val = False
        try:
            config_management_enabled_val = is_slssteam_config_management_enabled()
        except OSError as e:
            logger.error(f"Error checking config management status: {e}")

        # Start the worker thread
        threading.Thread(
            target=self._run_finalize_io_worker,
            args=(size_on_disk, config_management_enabled_val),
            daemon=True,
        ).start()

    def _run_finalize_io_worker(
        self, size_on_disk: int, config_enabled: bool
    ):
        """Background thread worker for post-download I/O"""
        try:
            self._finalize_acf_and_manifests(size_on_disk)
            self._persist_wrapper_metadata()
            self._finalize_platform_specifics(config_enabled)
            self._finalize_greenluma(config_enabled)

        except OSError as e:
            logger.error(
                f"Critical error in post-processing thread: {e}", exc_info=True
            )
        finally:
            # Thread-safe slot invocation
            QMetaObject.invokeMethod(
                self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
            )

    def _finalize_acf_and_manifests(self, size_on_disk: int):
        # 1. ACF
        self._create_acf_file(size_on_disk)

        # 2. Manifests
        self._move_manifests_to_depotcache()

        # 3. Depot Info
        selected_depots = self.game_data.get("selected_depots_list", [])
        all_manifests = self.game_data.get("manifests", {})
        if selected_depots and all_manifests:
            self._save_main_depot_info(self.game_data, selected_depots, all_manifests)

    def _persist_wrapper_metadata(self):
        """
        Persist wrapper metadata in the game's .DepotDownloader folder.
        Stores selected DLC IDs so uninstall can clean up AppList entries later.
        """
        if sys.platform != "win32":
            return

        if not self.game_data or not self.current_dest_path:
            return

        game_directory = get_game_directory(self.current_dest_path, self.game_data)
        selected_dlcs: List[str] = self.game_data.get("selected_dlcs") or []

        if persist_selected_dlcs(game_directory, selected_dlcs):
            appid = self.game_data.get("appid", "unknown")
            logger.debug(
                f"Persisted wrapper metadata for AppID {appid} with {len(selected_dlcs)} DLC ID(s)"
            )

    def _finalize_platform_specifics(self, config_enabled: bool):
        # 4. Linux Permissions
        if sys.platform != "linux":
            return

        self._set_linux_binary_permissions()
        if self.slssteam_mode_was_active and config_enabled:
            self._add_appids_to_slssteam_config()

    def _finalize_greenluma(self, config_enabled: bool):
        # 5. GreenLuma Files (Win32)
        if not (self.slssteam_mode_was_active and sys.platform == "win32"):
            return

        try:
            logger.info("Looking for Steam installation...")
            steam_path = steam_helpers.find_steam_install()
            if steam_path:
                logger.info(
                    f"Steam found at {steam_path}. Checking GreenLuma config..."
                )
                self._create_greenluma_applist_files(
                    steam_path, config_enabled=config_enabled
                )
                self._copy_greenluma_bin_files(
                    steam_path, config_enabled=config_enabled
                )
                logger.info("GreenLuma configuration check complete.")
            else:
                logger.warning(
                    "Steam installation not found, skipping GreenLuma config."
                )
        except OSError as e:
            logger.error(f"GreenLuma configuration failed: {e}", exc_info=True)

    @pyqtSlot()
    def _finalize_job_logic(self):
        """Called on Main Thread. Acts as a State Machine Conductor."""
        if self._should_prompt_for_steam_restart():
            self.main_window.job_queue.steam_restart_prompt_pending = True

        steamless_enabled = self.settings.value("use_steamless", False, type=bool)
        if steamless_enabled and not self.is_cancelling:
            if "steamless" not in self._job_steps_completed:
                self._job_steps_completed.add("steamless")
                self.main_window.drop_text_label.setText(
                    f"Running Steamless: {self.game_data.get('game_name', '')}"
                )
                self._start_steamless_processing()
                return

        achievements_enabled = self.settings.value(
            "generate_achievements", False, type=bool
        )
        if achievements_enabled and not self.is_cancelling:
            if "achievements" not in self._job_steps_completed:
                self._job_steps_completed.add("achievements")
                self.main_window.drop_text_label.setText(
                    f"Generating Achievements: {self.game_data.get('game_name', '')}"
                )
                self._start_achievement_generation()
                return

        # --- FINISH ---
        logger.info("All post-processing steps complete. Finishing job.")
        self.main_window.job_queue.jobs_completed_count += 1
        if not self.is_cancelling:
            self.main_window.game_manager.scan_steam_libraries_async()

        self.job_finished()

    def _should_prompt_for_steam_restart(self) -> bool:
        if self.is_cancelling:
            return False

        return self.slssteam_mode_was_active or self.library_mode_was_active

    @staticmethod
    def _save_main_depot_info(game_data, selected_depots, all_manifests):
        try:
            appid = game_data.get("appid")
            if not appid or not selected_depots:
                return

            main_depot_id = str(selected_depots[0])
            manifest_id = all_manifests.get(main_depot_id)
            if not manifest_id:
                return

            depots_dir = Path(get_base_path()) / "depots"
            depots_dir.mkdir(parents=True, exist_ok=True)
            depot_file = depots_dir / f"{appid}.depot"
            access_token = game_data.get("app_token", "")

            with open(depot_file, "w") as f:
                if access_token:
                    f.write(f"{main_depot_id}: {manifest_id}: {access_token}\n")
                else:
                    f.write(f"{main_depot_id}: {manifest_id}\n")
        except OSError as e:
            logger.error(f"Failed to save depot info: {e}")

    def _create_acf_file(self, size_on_disk):
        if not self.game_data or not self.current_dest_path:
            return

        try:
            write_acf_file(
                self.current_dest_path,
                self.game_data,
                size_on_disk,
                include_depots=sys.platform == "win32",
            )
        except OSError as e:
            logger.error(f"Error creating .acf file: {e}")

    def _move_manifests_to_depotcache(self):
        if not self.game_data or not self.current_dest_path:
            return

        temp_manifest_dir = os.path.join(tempfile.gettempdir(), "mistwalker_manifests")
        if not os.path.exists(temp_manifest_dir):
            return

        target_depotcache_dir = os.path.join(self.current_dest_path, "depotcache")

        try:
            os.makedirs(target_depotcache_dir, exist_ok=True)
            manifests_map = self.game_data.get("manifests", {})
            if not manifests_map:
                shutil.rmtree(temp_manifest_dir)
                return

            for depot_id, manifest_gid in manifests_map.items():
                manifest_filename = f"{depot_id}_{manifest_gid}.manifest"
                source_path = os.path.join(temp_manifest_dir, manifest_filename)
                dest_path = os.path.join(target_depotcache_dir, manifest_filename)
                if os.path.exists(source_path):
                    shutil.move(source_path, dest_path)

            shutil.rmtree(temp_manifest_dir)
        except OSError as e:
            logger.error(f"Failed to move manifests to depotcache: {e}")

    def _set_linux_binary_permissions(self):
        if not self.game_data or not self.current_dest_path:
            return

        game_directory = get_game_directory(self.current_dest_path, self.game_data)

        if os.path.exists(game_directory):
            self._run_chmod_recursive(game_directory)

    def _create_steamless_task(self, progress_handler):
        self.steamless_task = SteamlessTask()
        self.steamless_task.progress.connect(progress_handler)
        self.steamless_task.result.connect(self._on_steamless_complete)
        self.steamless_task.finished.connect(self._on_steamless_finished)
        self.steamless_task.error.connect(self._handle_steamless_task_error)
        return self.steamless_task

    def _reset_steamless_task(self):
        if self.steamless_task:
            self.steamless_task.stop()
            self.steamless_task = None

    def _start_steamless_processing(self):
        if not self.current_dest_path or not self.game_data:
            self._finalize_job_logic()
            return

        game_directory = get_game_directory(self.current_dest_path, self.game_data)

        if not os.path.exists(game_directory):
            self._finalize_job_logic()
            return

        logger.info("\n" + "=" * 40)
        logger.info("Starting Steamless DRM Removal...")

        steamless_task = self._create_steamless_task(logger.info)
        steamless_task.set_game_directory(game_directory)
        steamless_task.start()

        self._steamless_ran = True
        self._update_status_button_color()

    def run_steamless_manually(self, exe_path: str, game_name: Optional[str] = None):
        self._reset_steamless_task()

        self._steamless_game_name = game_name or os.path.basename(exe_path)
        self._steamless_progress_log = []
        self._steamless_manual_run = True

        logger.info(f"Starting manual Steamless processing for: {exe_path}")
        steamless_task = self._create_steamless_task(self._on_steamless_progress)
        steamless_task.set_target_exe(exe_path)
        steamless_task.start()

    def run_steamless_for_game(self, game_directory: str, game_name: str):
        self._reset_steamless_task()

        self._steamless_game_name = game_name
        self._steamless_progress_log = []
        self._steamless_manual_run = True

        logger.info(f"Starting manual Steamless processing for game: {game_name}")
        steamless_task = self._create_steamless_task(self._on_steamless_progress)
        steamless_task.set_game_directory(game_directory)
        steamless_task.start()

    @staticmethod
    def _run_chmod_recursive(game_directory) -> int:
        import stat

        linux_binary_extensions = {
            ".sh",
            ".bash",
            ".x86",
            ".x86_64",
            ".bin",
            ".run",
            ".elf",
            ".pck",
        }
        elf_magic = b"\x7fELF"
        shebang_magic = b"#!"

        chmod_count = 0

        for root, _, filenames in os.walk(game_directory):
            for filename in filenames:
                file_path = os.path.join(root, filename)

                if os.path.islink(file_path):
                    continue

                should_chmod = False
                filename_lower = filename.lower()

                if any(filename_lower.endswith(ext) for ext in linux_binary_extensions):
                    should_chmod = True
                elif "." not in filename:
                    try:
                        with open(file_path, "rb") as f:
                            header = f.read(4)
                            if header.startswith(elf_magic) or header.startswith(
                                shebang_magic
                            ):
                                should_chmod = True
                    except (IOError, OSError):
                        continue

                if should_chmod:
                    try:
                        file_stat = os.stat(file_path)
                        current_mode = file_stat.st_mode
                        if not (current_mode & stat.S_IXUSR):
                            new_mode = current_mode | 0o755
                            os.chmod(file_path, new_mode)
                            chmod_count += 1
                    except OSError:
                        pass

        return chmod_count

    def _on_steamless_progress(self, message):
        self._steamless_progress_log.append(message)
        logger.info(message)

    def _on_steamless_complete(self, success):
        logger.info("\n" + "=" * 40)
        if success:
            logger.info("Steamless processing completed successfully")
        else:
            logger.info("Steamless processing completed with warnings or no DRM found")

        self._steamless_success = success
        self._last_steamless_success = success

    def _on_steamless_finished(self):
        if self.steamless_task:
            QTimer.singleShot(0, self._clear_steamless_task)

        if self._steamless_manual_run:
            self._show_steamless_resume_dialog()
            self._steamless_manual_run = False
            self._steamless_success = None
            return

        if self._steamless_success is not None:
            self._steamless_success = None

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _clear_steamless_task(self):
        self.steamless_task = None

    def _show_steamless_resume_dialog(self):
        # Deferred import
        from ui.dialogs.steamless_resume import SteamlessResumeDialog

        exe_count = 0
        processed_count = 0
        had_error = self._steamless_error

        for message in self._steamless_progress_log:
            if "Found " in message and "executable(s)" in message:
                try:
                    parts = message.split()
                    for i, part in enumerate(parts):
                        if part == "Found" and i + 1 < len(parts):
                            exe_count = int(parts[i + 1])
                            break
                except ValueError:
                    pass

            if "Successfully processed:" in message:
                processed_count += 1
            if "Successfully unpacked file!" in message:
                processed_count += 1
                exe_count = max(exe_count, 1)
            if "No Steam DRM detected" in message:
                exe_count = max(exe_count, 1)

        actual_success = processed_count > 0 and not had_error

        dialog = SteamlessResumeDialog(
            game_name=self._steamless_game_name,
            exe_count=exe_count,
            processed_count=processed_count,
            success=actual_success,
            parent=self.main_window,
        )
        dialog.exec()
        self._steamless_progress_log = []
        self._steamless_game_name = ""

    def _handle_steamless_task_error(self, error_info):
        _, error_value, _ = error_info
        logger.error(f"Steamless processing failed: {error_value}")
        self._steamless_error = True
        if self.steamless_task:
            QTimer.singleShot(0, self._clear_steamless_task)

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _start_achievement_generation(self):
        if not self.game_data:
            self._finalize_job_logic()
            return

        app_id = self.game_data.get("appid")
        if not app_id:
            self._finalize_job_logic()
            return

        logger.info("\n" + "=" * 40)
        logger.info("Starting Steam Achievement Generation...")

        self.achievement_task = GenerateAchievementsTask()
        self.achievement_task.progress.connect(logger.info)

        self.achievement_task_runner = TaskRunner()
        self.achievement_worker = self.achievement_task_runner.run(
            self.achievement_task.run, app_id
        )
        self.achievement_task_runner.cleanup_complete.connect(
            self._on_achievement_task_cleanup
        )

        self._update_status_button_color()
        self._slscheevo_ran = True

        self.achievement_worker.finished.connect(
            self._on_achievement_generation_complete
        )
        self.achievement_worker.error.connect(self._handle_achievement_error)

    def _on_achievement_generation_complete(self, result):
        if result is None:
            success = False
            message = "Unknown error"
        else:
            success = result.get("success", False)
            message = result.get("message", "Unknown status")

        if success:
            logger.info(f"Achievement generation completed: {message}")
        else:
            logger.info(f"Achievement generation failed: {message}")

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _handle_achievement_error(self, error_info):
        _, error_value, _ = error_info
        logger.error(f"Achievement generation failed: {error_value}")
        self._slscheevo_error = True

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _on_achievement_task_cleanup(self):
        self.achievement_task_runner = None
        self.achievement_task = None
        self.achievement_worker = None
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _create_greenluma_applist_files(self, steam_path, config_enabled=True):
        if not config_enabled:
            return

        try:
            app_list_dir = os.path.join(steam_path, "AppList")
            if not os.path.exists(app_list_dir):
                os.makedirs(app_list_dir)

            if not self.game_data:
                return

            game_appid = self.game_data.get("appid")
            if not game_appid:
                return

            if not self._app_id_exists_in_applist(app_list_dir, game_appid):
                next_num = self._find_next_applist_number(app_list_dir)
                filepath = os.path.join(app_list_dir, f"{next_num}.txt")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(game_appid)
                logger.info(
                    f"Created GreenLuma file: {filepath} for AppID: {game_appid}"
                )

            selected_dlcs: List[str] = self.game_data.get("selected_dlcs") or []
            for dlc_id in selected_dlcs:
                if not self._app_id_exists_in_applist(app_list_dir, dlc_id):
                    next_num = self._find_next_applist_number(app_list_dir)
                    filepath = os.path.join(app_list_dir, f"{next_num}.txt")
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(str(dlc_id))
                    logger.info(f"Created GreenLuma file: {filepath} for DLC: {dlc_id}")

        except OSError as e:
            logger.error(f"Failed to create GreenLuma AppList files: {e}")

    @staticmethod
    def _copy_greenluma_bin_files(steam_path, config_enabled=True):
        if sys.platform != "win32":
            return
        if not config_enabled:
            return

        source_dir = Paths.deps()
        files_to_copy = ["NoQuestion.bin", "StealthMode.bin"]

        for filename in files_to_copy:
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(steam_path, filename)

            try:
                if os.path.exists(source_path):
                    if not os.path.exists(dest_path):
                        shutil.copy2(source_path, dest_path)
                        logger.info(f"Copied {filename} to Steam folder")
            except OSError:
                pass

    @staticmethod
    def _find_next_applist_number(app_list_dir):
        if not os.path.exists(app_list_dir):
            os.makedirs(app_list_dir)
            return 1
        max_num = 0
        try:
            for filename in os.listdir(app_list_dir):
                match = re.match(r"^(\d+)\.txt$", filename)
                if match:
                    num = int(match.group(1))
                    if num > max_num:
                        max_num = num
        except (OSError, ValueError):
            pass
        return max_num + 1

    @staticmethod
    def _app_id_exists_in_applist(app_list_dir, app_id_to_check):
        if not os.path.exists(app_list_dir):
            return False
        try:
            for filename in os.listdir(app_list_dir):
                if filename.lower().endswith(".txt"):
                    filepath = os.path.join(app_list_dir, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            if f.read().strip() == app_id_to_check:
                                return True
                    except OSError:
                        pass
        except OSError:
            pass
        return False

    def _handle_task_error(self, error_info):
        if self.is_cancelling:
            return
        if not self.is_processing:
            return

        _, error_value, _ = error_info
        QMessageBox.critical(
            self.main_window, "Error", f"An error occurred: {error_value}"
        )
        if not self.is_cancelling:
            self.job_finished()

    def job_finished(self):
        """Clean up after job completion"""
        if not self.is_processing:
            return

        logger.info(
            f"Job '{os.path.basename(self.current_job or 'Unknown')}' finished."
        )

        if self.game_data:
            self._last_installed_game = self.game_data.get("game_name", "Unknown")

        ddm_ok = not self.is_cancelling

        if not self._slscheevo_ran:
            slscheevo_ok = None
        elif self._slscheevo_error:
            slscheevo_ok = False
        else:
            slscheevo_ok = True

        if not self._steamless_ran:
            steamless_ok = None
        elif self._steamless_error:
            steamless_ok = False
        else:
            steamless_ok = True

        self._update_status_for_job(
            ddm_ok=ddm_ok,
            slscheevo_ok=slscheevo_ok,
            steamless_ok=steamless_ok,
        )

        self.main_window.ui_state.show_main_gif()
        self.main_window.progress_bar.setVisible(False)
        self.main_window.speed_label.setVisible(False)
        self.game_data = None
        self.current_dest_path = None
        self.current_job_metadata = None
        self.slssteam_mode_was_active = False
        self.library_mode_was_active = False
        self.is_processing = False

        self._update_status_button_color()
        self.current_job = None

        self.is_download_paused = False
        self.main_window.ui_state.pause_button.setVisible(False)
        self.main_window.ui_state.cancel_button.setVisible(False)
        self.download_task = None
        self.is_cancelling = False
        self._delete_files_on_cancel = None

        if self.speed_monitor_task:
            self.is_awaiting_speed_monitor_stop = True
            self._stop_speed_monitor()
        else:
            self.is_awaiting_speed_monitor_stop = False

        if self.download_runner is None:
            self.is_awaiting_download_stop = False

        if self.zip_task_runner is None:
            self.is_awaiting_zip_task_stop = False

        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _update_status_button_color(self):
        status = self.get_component_status()
        settings = self.main_window.settings
        accent_color = settings.value("accent_color", "#C06C84")

        ddm_status = status["ddm_status"]
        slscheevo_status = status["slscheevo_status"]
        steamless_status = status["steamless_status"]

        if (
            ddm_status == "error"
            or slscheevo_status == "error"
            or steamless_status == "error"
        ):
            overall_color = self.STATUS_ERROR
        elif (
            ddm_status == "in_progress"
            or slscheevo_status == "in_progress"
            or steamless_status == "in_progress"
        ):
            overall_color = self.STATUS_IN_PROGRESS
        elif ddm_status == "ok" or slscheevo_status == "ok" or steamless_status == "ok":
            overall_color = self.STATUS_OK
        else:
            overall_color = accent_color

        self.main_window.bottom_titlebar.update_colored_circle_button(
            self.main_window.bottom_titlebar.status_button, overall_color
        )
        self.main_window.bottom_titlebar.no_previous_state = False

    def toggle_pause(self):
        if not self.download_task:
            return

        self.is_download_paused = not self.is_download_paused

        try:
            self.download_task.toggle_pause(self.is_download_paused)
            if self.is_download_paused:
                self.main_window.ui_state.pause_button.setText("Retomar")
                self.main_window.drop_text_label.setText(
                    f"Pausado: {os.path.basename(self.current_job)}"
                )
                self._stop_speed_monitor()
            else:
                self.main_window.ui_state.pause_button.setText("Pausar")
                self.main_window.drop_text_label.setText(
                    f"Baixando: {os.path.basename(self.current_job)}"
                )
                self._start_speed_monitor()
        except Exception as e:
            logger.error(f"Failed to toggle pause: {e}")

    def cancel_current_job(self):
        if not self.download_task or not self.current_job:
            return

        reply = QMessageBox.question(
            self.main_window,
            "Cancel Job",
            f"Are you sure you want to cancel the download for '{
                os.path.basename(self.current_job)
            }'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.No:
            return

        logger.info(f"--- Cancelling job: {os.path.basename(self.current_job)} ---")
        self.is_cancelling = True
        if self.download_runner is not None:
            self.is_awaiting_download_stop = True

        existing_install = self._detect_existing_installation()
        self._delete_files_on_cancel = self._confirm_delete_on_cancel(existing_install)

        if self.download_task:
            self.download_task.stop()
        self._kill_download_process()

        if self.achievement_task:
            self.achievement_task.stop()

        if self.steamless_task:
            self.steamless_task.stop()

    def _detect_existing_installation(self) -> bool:
        if not self.current_dest_path or not self.game_data:
            return False

        current_job_metadata = self.current_job_metadata or {}
        install_path = current_job_metadata.get("install_path")
        if install_path and os.path.exists(install_path):
            return True

        steamapps_dir = os.path.join(self.current_dest_path, "steamapps")
        appmanifest_path = os.path.join(
            steamapps_dir,
            f"appmanifest_{self.game_data.get('appid', '')}.acf",
        )
        if os.path.exists(appmanifest_path):
            return True

        game_dir = get_game_directory(self.current_dest_path, self.game_data)
        if os.path.isdir(game_dir):
            try:
                with os.scandir(game_dir) as entries:
                    for _ in entries:
                        return True
            except OSError:
                return True

        return False

    def _confirm_delete_on_cancel(self, existing_install: bool) -> bool:
        if existing_install:
            message = (
                "Existing installation detected. Delete files for this canceled job?"
            )
            default_button = QMessageBox.StandardButton.No
        else:
            message = "Delete partially downloaded files for this job?"
            default_button = QMessageBox.StandardButton.Yes

        reply = QMessageBox.question(
            self.main_window,
            "Cancel Download",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _kill_download_process(self):
        if self.download_task and self.download_task.process:
            if psutil is None:
                logger.error("psutil unavailable; cannot terminate process safely.")
                return
            try:
                p = psutil.Process(self.download_task.process.pid)
                for child in p.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                p.kill()
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                logger.error(f"Failed to kill process: {e}")

            self.download_task.process = None
            self.download_task.process_pid = None

    def _cleanup_cancelled_job_files(self):
        if not self.game_data or not self.current_dest_path:
            return

        try:
            steamapps_dir = os.path.join(self.current_dest_path, "steamapps")
            common_dir = os.path.join(steamapps_dir, "common")
            game_dir = get_game_directory(self.current_dest_path, self.game_data)
            acf_path = os.path.join(
                steamapps_dir, f"appmanifest_{self.game_data['appid']}.acf"
            )

            if os.path.exists(game_dir):
                shutil.rmtree(game_dir)
            if os.path.exists(acf_path):
                os.remove(acf_path)

            temp_manifest_dir = os.path.join(
                tempfile.gettempdir(), "mistwalker_manifests"
            )
            if os.path.exists(temp_manifest_dir):
                shutil.rmtree(temp_manifest_dir)

            if not self.slssteam_mode_was_active:
                try:
                    if os.path.exists(common_dir):
                        os.rmdir(common_dir)
                    if os.path.exists(steamapps_dir):
                        os.rmdir(steamapps_dir)
                except OSError:
                    pass

        except OSError as e:
            logger.error(f"Failed during cancel cleanup: {e}")

    def download_slssteam(self, steam_path=None):
        if (
            self.slssteam_download_task is not None
            and self.slssteam_download_runner is not None
        ):
            return

        self.slssteam_download_task = DownloadSLSsteamTask(steam_path=steam_path)
        self.slssteam_download_task.progress.connect(self._handle_slssteam_progress)
        self.slssteam_download_task.progress_percentage.connect(
            self._handle_slssteam_progress_percentage
        )
        self.slssteam_download_task.completed.connect(
            self._on_slssteam_download_complete
        )
        self.slssteam_download_task.error.connect(self._handle_slssteam_download_error)

        self.slssteam_download_runner = TaskRunner()
        worker = self.slssteam_download_runner.run(self.slssteam_download_task.run)
        worker.error.connect(self._handle_task_error)

    @staticmethod
    def _handle_slssteam_progress(message):
        logger.info(f"SLSsteam: {message}")

    def _handle_slssteam_progress_percentage(self, percentage):
        pass

    def _on_slssteam_download_complete(self, message):
        logger.info(f"SLSsteam download completed: {message}")
        QMessageBox.information(
            self.main_window, "SLSsteam Installation Complete", message
        )
        self.slssteam_download_task = None
        self.slssteam_download_runner = None

    def _handle_slssteam_download_error(self):
        logger.error("SLSsteam download failed")
        QMessageBox.critical(
            self.main_window,
            "Error",
            "Failed to download SLSsteam. Check internet connection.",
        )
        self.slssteam_download_task = None
        self.slssteam_download_runner = None

    def cleanup(self):
        """Clean up all tasks during shutdown"""
        self._stop_speed_monitor()

        if self.download_task and self.download_task.process:
            self.download_task.stop()
            self._kill_download_process()

        if self.achievement_task:
            self.achievement_task.stop()

        if self.steamless_task:
            self.steamless_task.stop()

        TaskRunner.stop_all_active()

    def get_component_status(self):
        if self.is_processing:
            if self.download_task or self.zip_task:
                ddm_status = "in_progress"
                ddm_status_text = "Downloading..."
                slscheevo_status = self._last_slscheevo_status
                slscheevo_status_text = self._last_slscheevo_status_text
                steamless_status = self._last_steamless_status
                steamless_status_text = self._last_steamless_status_text
            elif self.steamless_task:
                ddm_status = "ok"
                ddm_status_text = "Completed"
                slscheevo_status = self._last_slscheevo_status
                slscheevo_status_text = self._last_slscheevo_status_text
                steamless_status = "in_progress"
                steamless_status_text = "Running..."
            elif self.achievement_task:
                ddm_status = "ok"
                ddm_status_text = "Completed"
                slscheevo_status = "in_progress"
                slscheevo_status_text = "Generating achievements..."
                steamless_status = self._last_steamless_status
                steamless_status_text = self._last_steamless_status_text
            else:
                ddm_status = self._last_ddm_status
                ddm_status_text = self._last_ddm_status_text
                slscheevo_status = self._last_slscheevo_status
                slscheevo_status_text = self._last_slscheevo_status_text
                steamless_status = self._last_steamless_status
                steamless_status_text = self._last_steamless_status_text
        else:
            ddm_status = self._last_ddm_status
            ddm_status_text = self._last_ddm_status_text
            slscheevo_status = self._last_slscheevo_status
            slscheevo_status_text = self._last_slscheevo_status_text
            steamless_status = self._last_steamless_status
            steamless_status_text = self._last_steamless_status_text

        return {
            "ddm_status": ddm_status,
            "ddm_status_text": ddm_status_text,
            "slscheevo_status": slscheevo_status,
            "slscheevo_status_text": slscheevo_status_text,
            "steamless_status": steamless_status,
            "steamless_status_text": steamless_status_text,
        }

    def _get_steamless_status_text(self):
        if self._last_steamless_success is None:
            return "Ready"
        elif self._last_steamless_success:
            return "Success"
        else:
            return "Completed (no DRM found)"

    def _update_status_for_job(self, ddm_ok=True, slscheevo_ok=None, steamless_ok=None):
        self._last_ddm_status = "ok" if ddm_ok else "error"
        self._last_ddm_status_text = "Completed" if ddm_ok else "Failed"

        if slscheevo_ok is None:
            self._last_slscheevo_status = "not_run"
            self._last_slscheevo_status_text = "N/A"
        else:
            self._last_slscheevo_status = "ok" if slscheevo_ok else "error"
            self._last_slscheevo_status_text = "Completed" if slscheevo_ok else "Failed"

        if steamless_ok is None:
            self._last_steamless_status = "not_run"
            self._last_steamless_status_text = "N/A"
        else:
            self._last_steamless_status = "ok" if steamless_ok else "error"
            self._last_steamless_status_text = self._get_steamless_status_text()
