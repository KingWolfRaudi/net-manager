#!/usr/bin/env python3
"""
Gestor de Redes WiFi para Ubuntu Server en Chromebook
Autor: [Tu Nombre]
"""

import subprocess
import json
import os
import sys
import time
from pathlib import Path

class WiFiManager:
    def __init__(self):
        self.interface = self.detect_wifi_interface()
        self.config_dir = Path.home() / '.wifi_configs'
        self.config_dir.mkdir(exist_ok=True)
    
    def run_command(self, command, sudo=False):
        """Ejecuta un comando en la terminal"""
        try:
            if sudo:
                command = ['sudo'] + command
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error ejecutando comando: {e}")
            return None
    
    def detect_wifi_interface(self):
        """Detecta la interfaz WiFi disponible"""
        try:
            result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'wl' in line:  # Interfaces WiFi suelen empezar con wl
                    return line.split(':')[1].strip()
        except:
            pass
        return 'wlan0'  # Valor por defecto
    
    def check_wifi_status(self):
        """Verifica el estado del WiFi"""
        print("🔍 Verificando estado del WiFi...")
        
        # Verificar si la interfaz está activa
        status = self.run_command(['ip', 'link', 'show', self.interface])
        if status and 'state UP' in status:
            print(f"✅ Interfaz {self.interface} activa")
        else:
            print(f"❌ Interfaz {self.interface} inactiva")
            return False
        
        # Verificar conexión a Internet
        try:
            subprocess.run(['ping', '-c', '1', '8.8.8.8'], 
                         capture_output=True, check=True)
            print("✅ Conexión a Internet activa")
            return True
        except:
            print("❌ Sin conexión a Internet")
            return False
    
    def scan_networks(self):
        """Escanea redes WiFi disponibles"""
        print("📡 Escaneando redes WiFi...")
        
        # Activar interfaz si no está activa
        self.run_command(['ip', 'link', 'set', self.interface, 'up'], sudo=True)
        time.sleep(2)
        
        # Escanear redes
        scan_result = self.run_command(['iwlist', self.interface, 'scan'])
        
        networks = []
        if scan_result:
            current_essid = None
            for line in scan_result.split('\n'):
                line = line.strip()
                if 'ESSID:' in line:
                    essid = line.split('ESSID:')[1].strip().strip('"')
                    if essid and essid != '\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00':
                        current_essid = essid
                        networks.append({'essid': essid, 'signal': 'N/A'})
                elif 'Signal level=' in line and current_essid:
                    signal = line.split('Signal level=')[1].split(' ')[0]
                    networks[-1]['signal'] = signal
        
        return networks
    
    def connect_to_network(self, ssid, password=None):
        """Conecta a una red WiFi"""
        print(f"🔗 Conectando a {ssid}...")
        
        # Usar nmcli si está disponible (NetworkManager)
        if self.run_command(['which', 'nmcli']):
            return self.connect_with_nmcli(ssid, password)
        else:
            return self.connect_with_wpa_supplicant(ssid, password)
    
    def connect_with_nmcli(self, ssid, password):
        """Conectar usando NetworkManager"""
        if password:
            cmd = ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
        else:
            cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
        
        result = self.run_command(cmd, sudo=True)
        if result and 'successfully activated' in result:
            print(f"✅ Conectado exitosamente a {ssid}")
            return True
        else:
            print(f"❌ Error conectando a {ssid}")
            return False
    
    def connect_with_wpa_supplicant(self, ssid, password):
        """Conectar usando wpa_supplicant (método tradicional)"""
        if not password:
            print("❌ Se requiere contraseña para esta red")
            return False
        
        # Crear configuración WPA
        config_content = f"""
network={{
    ssid="{ssid}"
    psk="{password}"
}}
"""
        
        config_file = self.config_dir / f'{ssid}.conf'
        with open(config_file, 'w') as f:
            f.write(config_content)
        
        # Detener procesos existentes
        self.run_command(['pkill', 'wpa_supplicant'], sudo=True)
        time.sleep(1)
        
        # Conectar
        cmd = [
            'wpa_supplicant', '-B', '-i', self.interface,
            '-c', str(config_file)
        ]
        
        result = self.run_command(cmd, sudo=True)
        time.sleep(3)
        
        # Obtener IP via DHCP
        self.run_command(['dhclient', self.interface], sudo=True)
        
        if self.check_wifi_status():
            print(f"✅ Conectado exitosamente a {ssid}")
            return True
        else:
            print(f"❌ Error conectando a {ssid}")
            return False
    
    def save_network_config(self, ssid, password):
        """Guarda la configuración de red de forma segura"""
        config_file = self.config_dir / 'saved_networks.json'
        
        # Cargar configuraciones existentes
        if config_file.exists():
            with open(config_file, 'r') as f:
                networks = json.load(f)
        else:
            networks = {}
        
        # Guardar nueva configuración
        networks[ssid] = {
            'password': password,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        with open(config_file, 'w') as f:
            json.dump(networks, f, indent=2)
        
        # Cambiar permisos para seguridad
        os.chmod(config_file, 0o600)
        print(f"✅ Configuración de {ssid} guardada")
    
    def list_saved_networks(self):
        """Lista las redes guardadas"""
        config_file = self.config_dir / 'saved_networks.json'
        
        if not config_file.exists():
            print("📝 No hay redes guardadas")
            return []
        
        with open(config_file, 'r') as f:
            networks = json.load(f)
        
        print("📋 Redes guardadas:")
        for ssid, info in networks.items():
            print(f"  • {ssid} (guardada: {info['saved_at']})")
        
        return list(networks.keys())
    
    def disconnect(self):
        """Desconecta de la red WiFi actual"""
        print("🔌 Desconectando WiFi...")
        
        if self.run_command(['which', 'nmcli']):
            self.run_command(['nmcli', 'device', 'disconnect', self.interface], sudo=True)
        else:
            self.run_command(['pkill', 'wpa_supplicant'], sudo=True)
            self.run_command(['ip', 'link', 'set', self.interface, 'down'], sudo=True)
        
        print("✅ WiFi desconectado")

def main():
    manager = WiFiManager()
    
    while True:
        print("\n" + "="*50)
        print("🌐 GESTOR DE REDES WiFi")
        print("="*50)
        print("1. Verificar estado del WiFi")
        print("2. Escanear redes disponibles")
        print("3. Conectar a red WiFi")
        print("4. Listar redes guardadas")
        print("5. Desconectar WiFi")
        print("6. Salir")
        print("-"*50)
        
        choice = input("Selecciona una opción (1-6): ").strip()
        
        if choice == '1':
            manager.check_wifi_status()
        
        elif choice == '2':
            networks = manager.scan_networks()
            if networks:
                print("\n📶 Redes disponibles:")
                for i, network in enumerate(networks, 1):
                    print(f"  {i}. {network['essid']} (Señal: {network['signal']})")
            else:
                print("❌ No se encontraron redes WiFi")
        
        elif choice == '3':
            ssid = input("Nombre de la red (SSID): ").strip()
            if not ssid:
                print("❌ El nombre de la red no puede estar vacío")
                continue
            
            password = input("Contraseña (dejar vacío si es abierta): ").strip()
            
            if manager.connect_to_network(ssid, password):
                save = input("¿Guardar esta configuración? (s/n): ").strip().lower()
                if save == 's' and password:
                    manager.save_network_config(ssid, password)
        
        elif choice == '4':
            manager.list_saved_networks()
        
        elif choice == '5':
            manager.disconnect()
        
        elif choice == '6':
            print("👋 ¡Hasta luego!")
            break
        
        else:
            print("❌ Opción no válida")
        
        input("\nPresiona Enter para continuar...")

if __name__ == "__main__":
    # Verificar si se ejecuta como root
    if os.geteuid() != 0:
        print("🔒 Este script requiere permisos de superusuario")
        print("Ejecuta: sudo python3 wifi_manager.py")
        sys.exit(1)
    
    main()