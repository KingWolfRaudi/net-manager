#!/usr/bin/env python3
"""
Gestor de Redes WiFi para Ubuntu Server con Netplan
Especial para Chromebook con Ubuntu Server
"""

import subprocess
import os
import sys
import time
import yaml
import shutil
from pathlib import Path

class NetplanWiFiManager:
    def __init__(self):
        self.interface = self.detect_wifi_interface()
        self.netplan_dir = Path('/etc/netplan')
        self.backup_dir = Path('/etc/netplan/backups')
        self.backup_dir.mkdir(exist_ok=True)
        
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
                if 'wl' in line and 'BROADCAST' in line:
                    return line.split(':')[1].strip()
        except:
            pass
        
        # Si no detecta, probar interfaces comunes
        for iface in ['wlan0', 'wlp1s0', 'wlp2s0']:
            try:
                subprocess.run(['ip', 'link', 'show', iface], capture_output=True, check=True)
                return iface
            except:
                continue
        
        return 'wlan0'
    
    def backup_netplan_config(self):
        """Crea un backup de la configuración actual de netplan"""
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        for config_file in self.netplan_dir.glob('*.yaml'):
            backup_file = self.backup_dir / f"{config_file.stem}_{timestamp}.yaml"
            shutil.copy2(config_file, backup_file)
            print(f"✅ Backup creado: {backup_file}")
    
    def get_current_netplan_config(self):
        """Obtiene la configuración actual de netplan"""
        config_files = list(self.netplan_dir.glob('*.yaml'))
        if not config_files:
            return None
        
        main_config = config_files[0]  # Usualmente 50-cloud-init.yaml o 01-netcfg.yaml
        with open(main_config, 'r') as f:
            return yaml.safe_load(f)
    
    def scan_wifi_networks(self):
        """Escanea redes WiFi disponibles usando iwlist"""
        print("📡 Escaneando redes WiFi...")
        
        # Activar interfaz temporalmente para escanear
        self.run_command(['ip', 'link', 'set', self.interface, 'up'], sudo=True)
        time.sleep(2)
        
        try:
            # Escanear con iwlist
            scan_result = self.run_command(['iwlist', self.interface, 'scan'], sudo=True)
            networks = []
            current_essid = None
            
            for line in scan_result.split('\n'):
                line = line.strip()
                if 'ESSID:' in line:
                    essid = line.split('ESSID:')[1].strip().strip('"')
                    if essid and essid not in ['', '\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00']:
                        current_essid = essid
                        networks.append({'essid': essid, 'encryption': 'Desconocido'})
                elif 'Encryption key:' in line and current_essid:
                    if 'on' in line:
                        networks[-1]['encryption'] = 'Protegida'
                    else:
                        networks[-1]['encryption'] = 'Abierta'
                elif 'IE: WPA' in line and current_essid:
                    networks[-1]['encryption'] = 'WPA'
                elif 'IE: IEEE 802.11i/WPA2' in line and current_essid:
                    networks[-1]['encryption'] = 'WPA2'
            
            return networks
            
        except Exception as e:
            print(f"❌ Error escaneando redes: {e}")
            return []
    
    def create_netplan_config(self, ssid, password=None, dhcp=True, static_ip=None):
        """Crea configuración netplan para WiFi"""
        
        # Configuración base
        config = {
            'network': {
                'version': 2,
                'renderer': 'networkd',
                'wifis': {
                    self.interface: {
                        'access-points': {
                            ssid: {} if not password else {'password': password}
                        },
                        'dhcp4': dhcp
                    }
                }
            }
        }
        
        # Configuración IP estática si se especifica
        if static_ip and not dhcp:
            config['network']['wifis'][self.interface]['dhcp4'] = False
            config['network']['wifis'][self.interface]['addresses'] = [static_ip]
            if 'gateway4' in static_ip:
                config['network']['wifis'][self.interface]['gateway4'] = static_ip['gateway']
            if 'nameservers' in static_ip:
                config['network']['wifis'][self.interface]['nameservers'] = static_ip['nameservers']
        
        return config
    
    def connect_to_wifi(self, ssid, password=None, dhcp=True, static_ip=None):
        """Conecta a una red WiFi usando netplan"""
        print(f"🔗 Configurando conexión a '{ssid}'...")
        
        try:
            # Crear backup
            self.backup_netplan_config()
            
            # Obtener configuración actual
            current_config = self.get_current_netplan_config()
            if not current_config:
                current_config = {'network': {'version': 2, 'renderer': 'networkd'}}
            
            # Agregar configuración WiFi
            if 'wifis' not in current_config['network']:
                current_config['network']['wifis'] = {}
            
            current_config['network']['wifis'][self.interface] = {
                'access-points': {
                    ssid: {} if not password else {'password': password}
                },
                'dhcp4': dhcp
            }
            
            # Configuración estática si se especifica
            if static_ip and not dhcp:
                current_config['network']['wifis'][self.interface]['dhcp4'] = False
                current_config['network']['wifis'][self.interface]['addresses'] = [static_ip['address']]
                if 'gateway' in static_ip:
                    current_config['network']['wifis'][self.interface]['gateway4'] = static_ip['gateway']
                if 'dns' in static_ip:
                    current_config['network']['wifis'][self.interface]['nameservers'] = {'addresses': static_ip['dns']}
            
            # Escribir nuevo archivo de configuración
            config_file = self.netplan_dir / '99-wifi-config.yaml'
            with open(config_file, 'w') as f:
                yaml.dump(current_config, f, default_flow_style=False)
            
            print("✅ Configuración netplan guardada")
            
            # Aplicar configuración
            return self.apply_netplan_config()
            
        except Exception as e:
            print(f"❌ Error configurando WiFi: {e}")
            return False
    
    def apply_netplan_config(self):
        """Aplica la configuración de netplan"""
        try:
            print("🔄 Aplicando configuración netplan...")
            
            # Generar y aplicar configuración
            result = self.run_command(['netplan', 'generate'], sudo=True)
            if result is None:
                return False
            
            result = self.run_command(['netplan', 'apply'], sudo=True)
            if result is None:
                return False
            
            print("⏳ Esperando que la conexión se establezca...")
            time.sleep(10)
            
            # Verificar conexión
            return self.check_connection()
            
        except Exception as e:
            print(f"❌ Error aplicando netplan: {e}")
            return False
    
    def check_connection(self):
        """Verifica el estado de la conexión"""
        print("🔍 Verificando conexión...")
        
        # Verificar interfaz
        interface_status = self.run_command(['ip', 'addr', 'show', self.interface])
        if not interface_status:
            print(f"❌ Interfaz {self.interface} no encontrada")
            return False
        
        if 'state UP' in interface_status:
            print(f"✅ Interfaz {self.interface} activa")
        else:
            print(f"❌ Interfaz {self.interface} inactiva")
            return False
        
        # Verificar IP
        if 'inet ' in interface_status:
            for line in interface_status.split('\n'):
                if 'inet ' in line:
                    ip = line.split()[1]
                    print(f"📡 Dirección IP: {ip}")
                    break
        else:
            print("❌ Sin dirección IP asignada")
            return False
        
        # Verificar conectividad a Internet
        try:
            print("🌐 Probando conectividad a Internet...")
            subprocess.run(['ping', '-c', '3', '-W', '5', '8.8.8.8'], 
                         capture_output=True, check=True)
            print("✅ Conexión a Internet activa")
            return True
        except:
            print("⚠️  Tiene IP pero sin conexión a Internet")
            return True  # Considerar éxito si tiene IP
    
    def disconnect_wifi(self):
        """Desconecta el WiFi eliminando configuración netplan"""
        print("🔌 Desconectando WiFi...")
        
        try:
            # Eliminar configuraciones WiFi personalizadas
            for config_file in self.netplan_dir.glob('99-*.yaml'):
                backup_file = self.backup_dir / f"disconnect_backup_{config_file.name}"
                shutil.copy2(config_file, backup_file)
                self.run_command(['rm', '-f', str(config_file)], sudo=True)
                print(f"✅ Configuración eliminada: {config_file}")
            
            # Aplicar cambios
            self.run_command(['netplan', 'apply'], sudo=True)
            print("✅ WiFi desconectado")
            
        except Exception as e:
            print(f"❌ Error desconectando WiFi: {e}")
    
    def list_saved_networks(self):
        """Lista redes guardadas en netplan"""
        print("📋 Redes configuradas en netplan:")
        
        config = self.get_current_netplan_config()
        if not config or 'wifis' not in config['network']:
            print("   No hay redes WiFi configuradas")
            return
        
        for interface, settings in config['network']['wifis'].items():
            if 'access-points' in settings:
                for ssid in settings['access-points']:
                    print(f"   • {ssid} (interface: {interface})")
    
    def get_interface_status(self):
        """Obtiene estado detallado de la interfaz"""
        print(f"📊 Estado de {self.interface}:")
        
        # Información de la interfaz
        info = self.run_command(['ip', 'addr', 'show', self.interface])
        if info:
            for line in info.split('\n'):
                if 'inet ' in line:
                    print(f"   IP: {line.strip()}")
                elif 'state ' in line:
                    print(f"   Estado: {line.strip()}")
        
        # Conexión WiFi actual
        wifi_info = self.run_command(['iwconfig', self.interface])
        if wifi_info:
            for line in wifi_info.split('\n'):
                if 'ESSID:' in line:
                    print(f"   Red: {line.strip()}")
                elif 'Signal level=' in line:
                    print(f"   Señal: {line.strip()}")

def main():
    manager = NetplanWiFiManager()
    
    print(f"🌐 Gestor WiFi Netplan - Interfaz: {manager.interface}")
    
    while True:
        print("\n" + "="*50)
        print("📡 GESTOR WiFi CON NETPLAN")
        print("="*50)
        print("1. Escanear redes disponibles")
        print("2. Conectar a red WiFi (DHCP)")
        print("3. Conectar a red WiFi (IP estática)")
        print("4. Ver estado de conexión")
        print("5. Listar redes configuradas")
        print("6. Desconectar WiFi")
        print("7. Salir")
        print("-"*50)
        
        choice = input("Selecciona una opción (1-7): ").strip()
        
        if choice == '1':
            networks = manager.scan_wifi_networks()
            if networks:
                print("\n📶 Redes disponibles:")
                for i, network in enumerate(networks, 1):
                    print(f"  {i}. {network['essid']} - {network['encryption']}")
            else:
                print("❌ No se encontraron redes WiFi")
        
        elif choice == '2':
            ssid = input("Nombre de la red (SSID): ").strip()
            if not ssid:
                print("❌ El SSID no puede estar vacío")
                continue
            
            password = None
            encryption = input("¿La red tiene contraseña? (s/n): ").strip().lower()
            if encryption == 's':
                password = input("Contraseña: ").strip()
            
            if manager.connect_to_wifi(ssid, password):
                print(f"✅ Conectado exitosamente a {ssid}")
            else:
                print(f"❌ Error conectando a {ssid}")
        
        elif choice == '3':
            ssid = input("Nombre de la red (SSID): ").strip()
            if not ssid:
                print("❌ El SSID no puede estar vacío")
                continue
            
            password = None
            encryption = input("¿La red tiene contraseña? (s/n): ").strip().lower()
            if encryption == 's':
                password = input("Contraseña: ").strip()
            
            ip = input("Dirección IP estática (ej: 192.168.1.100/24): ").strip()
            gateway = input("Gateway (ej: 192.168.1.1): ").strip()
            dns = input("DNS (ej: 8.8.8.8,8.8.4.4): ").strip().split(',')
            
            static_config = {
                'address': ip,
                'gateway': gateway,
                'dns': dns
            }
            
            if manager.connect_to_wifi(ssid, password, dhcp=False, static_ip=static_config):
                print(f"✅ Conectado exitosamente a {ssid} con IP estática")
            else:
                print(f"❌ Error conectando a {ssid}")
        
        elif choice == '4':
            manager.get_interface_status()
            manager.check_connection()
        
        elif choice == '5':
            manager.list_saved_networks()
        
        elif choice == '6':
            manager.disconnect_wifi()
        
        elif choice == '7':
            print("👋 ¡Hasta luego!")
            break
        
        else:
            print("❌ Opción no válida")
        
        input("\nPresiona Enter para continuar...")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("🔒 Este script requiere permisos de superusuario")
        print("Ejecuta: sudo python3 netplan_wifi_manager.py")
        sys.exit(1)
    
    # Verificar que netplan está disponible
    if shutil.which('netplan') is None:
        print("❌ Netplan no está instalado")
        print("Instala con: sudo apt install netplan.io")
        sys.exit(1)
    
    main()