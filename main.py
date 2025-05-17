import os
import uuid
import json
import zipfile
import hashlib
import threading
import subprocess
import logging
import shutil
from pathlib import Path

import requests
import psutil
import webview
import minecraft_launcher_lib

launcherVersion = "0.1.4"
launcher_name = "YummyCraft Launcher"
launcher_dir = "yummycraft"
ams = "https://yummycraft.pro"

minecraft_directory = minecraft_launcher_lib.utils.get_minecraft_directory().replace('minecraft', launcher_dir)
builds_path = Path(minecraft_directory) / "builds"
config_path = Path(minecraft_directory) / "launcher_config.json"
log_path = Path(minecraft_directory) / "launcher_logs.txt"


os.makedirs(minecraft_directory, exist_ok=True)
os.makedirs(builds_path, exist_ok=True)

os.chdir(minecraft_directory)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8")
    ]
)


def check_logs():
    if os.path.exists(log_path):
        if os.path.getsize(log_path) > 15 * 1024 * 1024:
            with open(log_path, "w"):
                pass
            logging.info("Файл логов очищен (превышен лимит 15MB)")


def get_first_mac_address():
    try:
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == psutil.AF_LINK:
                    return addr.address
        return None
    except Exception as e:
        logging.error(f"Ошибка при получении MAC-адреса: {e}")
        return None


def set_status_message(message: str):
    try:
        safe_msg = message.replace('"', '\\"')
        
        window.evaluate_js(f"""
            const el = document.querySelector('.status-message');
            if (el) {{
                el.innerText = "{safe_msg}";
            }}
        """)
    except Exception as e:
        logging.error(f"Ошибка при обновлении прогресса: {e}")


def get_total_ram_mb():
    total_bytes = psutil.virtual_memory().total
    return total_bytes // (1024 * 1024)



class ConfigManager:
    def __init__(self):
        self.config_path = Path(config_path)
        self.create_config()

    def create_config(self):
        if not os.path.exists(self.config_path):
            default_config = {
                "ams": ams,
                "nickname": "",
                "ram": "1024",
                "jvm_args": "",
                "resolution_x": "",
                "resolution_y": "",
                "java_path": ""
            }
            with open(self.config_path, "w") as f:
                json.dump(default_config, f, indent=4)

    def load_config(self):
        with open(self.config_path, "r") as f:
            return json.load(f)

    def save_config(self, config):
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=4)

    def open_folder(self):
        if os.name == 'nt':
            subprocess.run(['explorer', minecraft_directory])
        elif os.name == 'posix':
            if 'darwin' in os.uname().sysname.lower():
                subprocess.run(['open', minecraft_directory])
            else:
                subprocess.run(['xdg-open', minecraft_directory])
        else:
            logging.error(f"Неизвестная операционная система. Не удается открыть папку.")

    def get_ams(self):
        with open(self.config_path, "r") as f:
            config = json.load(f)
        return config.get("ams", None)


class ModManager:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.api_url = self.config_manager.get_ams()

    def download_mod(self, mod_name, server_name, mods_directory):
        local_path = mods_directory / mod_name

        try:
            response = requests.get(url = f"{self.api_url}/launcher/{server_name}/download_mod/{mod_name}", stream=True, verify=True)
            if response.status_code == 200:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0

                with open(local_path, "wb") as file:
                    for chunk in response.iter_content(1024):
                        file.write(chunk)
                        downloaded += len(chunk)
                        percent = int(downloaded * 100 / total_size)
                        set_status_message(f"Скачивание {mod_name}: {percent}%")

                logging.info(f"Мод {mod_name} успешно скачан.")

                set_status_message(f"Мод {mod_name} успешно скачан ✅")
            else:
                logging.error(f"Не удалось скачать {mod_name}: {response.status_code}")
                set_status_message(f"Не удалось скачать {mod_name} ❌")
        except requests.exceptions.RequestException as e:
            logging.error(f"Ошибка при скачивании {mod_name}: {e}")
            set_status_message(f"Ошибка при скачивании {mod_name} ❌")

    def get_remote_mods_dict(self, server_name):
        response = requests.get(url = f"{self.api_url}/launcher/{server_name}/list_mod", verify=True)
        if response.status_code == 200:
            return response.json()

    def get_local_mods_dict(self, mods_directory):
        files = {}
        for f in mods_directory.iterdir():
            if f.is_file():
                with open(f, "rb") as file:
                    file_hash = hashlib.sha256(file.read()).hexdigest()
                    files[f.name] = file_hash
        return files

    def check_mods(self, server_name):
        
        mods_directory = Path(f"{builds_path}/{server_name}/mods")
        os.makedirs(mods_directory, exist_ok=True)

        remote_mods = self.get_remote_mods_dict(server_name)
        local_mods = self.get_local_mods_dict(mods_directory)

        for local_mod in list(local_mods.keys()):
            if local_mod not in remote_mods:
                local_mod_path = mods_directory / local_mod
                os.remove(local_mod_path)
                logging.info(f"Удалён мод: {local_mod}")
                set_status_message(f"Удалён мод: {local_mod}")

        for remote_mod, remote_hash in remote_mods.items():
            local_hash = local_mods.get(remote_mod)

            if local_hash != remote_hash:
                if local_hash is None:
                    logging.info(f"Мод {remote_mod} отсутствует локально. Скачиваем.")
                    set_status_message(f"Мод {remote_mod} отсутствует локально. Скачиваем...")
                else:
                    logging.info(f"Хэш мода {remote_mod} не совпадает. Обновляем мод.")
                    set_status_message(f"Хэш мода {remote_mod} не совпадает. Обновляем мод...")
                self.download_mod(remote_mod, server_name, mods_directory)


class VersionManager:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.api_url = self.config_manager.get_ams()
        self.minecraft_dir = minecraft_directory

    def check_fabric_version(self, server_name, required_version):
        installed_versions = minecraft_launcher_lib.utils.get_installed_versions(f"{builds_path}/{server_name}")

        found = False
        for version in installed_versions:
            if version["id"] == required_version:
                found = True
                break

        if not found:
            logging.info(f"Требуемая версия {required_version} не найдена. Начинаем скачивание...")
            set_status_message(f"Требуемая версия {required_version} не найдена. Начинаем скачивание...")
            self.download_fabric_base(server_name)
        else:
            logging.info(f"Требуемая версия {required_version} уже установлена.")
            set_status_message(f"Требуемая версия {required_version} уже установлена.")

        
    def download_fabric_base(self, server_name):
        build_path = Path(builds_path) / server_name

        os.makedirs(build_path, exist_ok=True)
        
        local_zip_path = Path(build_path) / "base_fabric.zip"


        response = requests.get(url = f"{self.api_url}/launcher/{server_name}/download_fabric", stream=True, verify=True)
        if response.status_code == 200:
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            last_percent = 0

            with open(local_zip_path, 'wb') as file:
                for data in response.iter_content(1024):
                    file.write(data)
                    downloaded += len(data)
                    percent = int(downloaded * 100 / total_size)

                    if percent > last_percent:
                        set_status_message(f"Скачивание: {percent}%")
                        last_percent = percent

            set_status_message(f"Скачивание завершено.")

            try:
                set_status_message("Распаковка файлов...")
                with zipfile.ZipFile(local_zip_path, 'r') as zip_ref:
                    zip_ref.extractall(build_path)
            except Exception as e:
                logging.error(f"Ошибка при распаковке архива: {e}")

            try:
                os.remove(local_zip_path)
            except Exception as e:
                logging.error(f"Ошибка при удалении архива: {e}")

            set_status_message("Готово ✅")
        else:
            logging.error(f"Ошибка при скачивании файла. Код ошибки: {response.status_code}")
            set_status_message("Ошибка при скачивании ❌")

    def delete_build(self, server_name):
        build_path = Path(builds_path) / server_name
        try:
            shutil.rmtree(build_path)
            logging.info(f"Сборка '{server_name}' успешно удалена.")
        except Exception as e:
            logging.error(f"Ошибка при удалении сборки '{server_name}': {e}")


class Launcher:
    def __init__(self):
        self.version_manager = VersionManager()
        self.mod_manager = ModManager()
        self.config_manager = ConfigManager()

    def close(self):
        os._exit(0)

    def play_game(self, server_name, required_version):
        
        logging.info(f"Запуск сервера: {server_name}")

        def on_game_start():
            if window:
                window.evaluate_js("document.getElementById('game-status').style.display = 'block';")
                window.evaluate_js("document.getElementById('launcher').style.display = 'none';")

        def on_game_end():
            if window:
                window.show()
                window.evaluate_js("document.getElementById('game-status').style.display = 'none';")
                window.evaluate_js("document.getElementById('launcher').style.display = 'flex';")

        def run():

            on_game_start()


            self.version_manager.check_fabric_version(server_name, required_version)
            self.mod_manager.check_mods(server_name)

            set_status_message(f"Игра запущена...")
            logging.info(f"Игра запущена...")


            mac_address = get_first_mac_address()
            generated_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, mac_address))

            config = self.config_manager.load_config()

            nickname = config.get("nickname", "Player")
            ram = config.get("ram", "")
            jvm_args = config.get("jvm_args", "")
            java_path = config.get("java_path", "java") or "java"
            res_x = config.get("resolution_x", "")
            res_y = config.get("resolution_y", "")

            customResolution = bool(res_x and res_y)

            jvm_args = config.get("jvm_args", "").strip()
            jvm_arguments = [f"-Xmx{ram}M"]

            if jvm_args:
                jvm_arguments.extend(jvm_args.split())

            instance_directory = str(Path(builds_path) / server_name)

            options = {
                'executablePath': java_path,
                'launcherVersion': launcherVersion,
                'gameDirectory': instance_directory,
                'username': nickname,
                'uuid': generated_uuid,
                'jvmArguments': jvm_arguments,
                'customResolution': customResolution,
                "resolutionWidth": res_x,
                "resolutionHeight": res_y,
                'launcherName': launcher_name,
                'session_id': '',
            }

            command = minecraft_launcher_lib.command.get_minecraft_command(
                version=required_version,
                minecraft_directory=instance_directory,
                options=options
            )
            window.hide()

            try:
                if os.name == 'nt':
                    process = subprocess.Popen(command, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    process = subprocess.Popen(command, shell=False)

                process.wait()
                on_game_end()

                window.show()
            
            except Exception as e:
                logging.error(f"Ошибка при запуске игры: {e}")
                os._exit(0)


        threading.Thread(target=run).start()


class LauncherAPI:
    def __init__(self):
        self.launcher = Launcher()
        self.config_manager = ConfigManager()
        self.version_manager = VersionManager()

    def save_config(self, config):
        return self.config_manager.save_config(config)

    def get_config_data(self):
        return self.config_manager.load_config()

    def open_folder(self):
        return self.config_manager.open_folder()

    def play_game(self, server_name, version):
        return self.launcher.play_game(server_name, version)

    def delete_build(self, server_name):
        return self.version_manager.delete_build(server_name)

    def get_total_ram(self):
        return get_total_ram_mb()


class WebviewStart:
    def __init__(self):
        self.api = LauncherAPI()
        self.config_manager = ConfigManager()
        self.api_url = self.config_manager.get_ams()

    def create_window(self):
        try:
            response = requests.get(f"{self.api_url}/launcher/ui/config")
            response.raise_for_status()
            config_ui = response.json()
            logging.info(f"UI-конфиг успешно загружен")
        except Exception as e:
            logging.error(f"Ошибка загрузки UI-конфига: {e}")
            config_ui = {
                "title": launcher_name,
                "background_color": "#222222",
                "min_size": [600, 400],
                "transparent": False,
                "frameless": False,
                "resizable": True,
                "height": 600,
                "width": 900,
        }

        config_ui["url"] = f"{self.api_url}/launcher/ui/index.html"
        config_ui["js_api"] = self.api

        return webview.create_window(**config_ui)



if __name__ == "__main__":
    check_logs()
    window = WebviewStart().create_window()
    webview.start()
