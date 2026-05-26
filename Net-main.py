#!/usr/bin/env python3
"""
Gestor de Redes WiFi para Ubuntu Server con Netplan
Optimizado para hardware nativo (Standalone)
"""

import subprocess
import os
import sys
import time
import yaml
import shutil
import ipaddress
from pathlib import Path

class NetplanWiFiManager:
    def __init__(self):
        self.interface = self.detect_wifi_interface()
        self.netplan_dir = Path('/etc/netplan')
        self.backup_dir = Path('/etc/netplan/backups')
        self.backup_dir.mkdir(exist_ok=True)
        self.wifi_config_file = self.netplan_dir / '99-wifi-config.yaml'
        
    def run_command(self, command, sudo=False, show_errors=False):
        """Ejecuta un comando en la terminal. Permite mostrar errores críticos."""
        try:
            if sudo:
                command = ['sudo'] + command
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if show_errors:
                print(f"\n⚠️  [DEBUG DEL SISTEMA] Detalle del error:")
                print(f"Comando: {' '.join(command)}")
                print(f"Error: {e.stderr.strip() if e.stderr else 'Sin salida de error'}\n")
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
        
        for iface in ['wlan0', 'wlp1s0', 'wlp2s0']:
            try:
                subprocess.run(['ip', 'link', 'show', iface], capture_output=True, check=True)
                return iface
            except:
                continue
        
        return 'wlan0' 
    
    def backup_netplan_config(self):
        """Crea un backup de la configuración WiFi actual"""
        if self.wifi_config_file.exists():
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            backup_file = self.backup_dir / f"99-wifi-config_{timestamp}.yaml"
            shutil.copy2(self.wifi_config_file, backup_file)
            print(f"✅ Backup creado: {backup_file}")
    
    def scan_wifi_networks(self):
        """Escanea redes WiFi con sistema de reintentos para hardware ocupado"""
        print("📡 Preparando tarjeta de red y escaneando...")
        
        # Activar interfaz
        self.run_command(['ip', 'link', 'set', self.interface, 'up'], sudo=True)
        
        # Sistema de reintentos (3 intentos)
        scan_result = None
        for intento in range(3):
            time.sleep(3) # Dar tiempo al hardware para despertar
            scan_result = self.run_command(['iw', 'dev', self.interface, 'scan'], sudo=True)
            
            if scan_result:
                break
            else:
                print(f"⏳ El adaptador está inicializando... reintentando (Intento {intento + 1}/3)")
        
        if not scan_result:
            print("❌ Error: La interfaz sigue ocupada. Intenta revisar si el modo avión (rfkill) está activado.")
            return []

        networks = {}
        current_bss = None
        
        for line in scan_result.split('\n'):
            line = line.strip()
            if line.startswith('BSS '):
                current_bss = line.split()[1].split('(')[0]
                networks[current_bss] = {'essid': 'Oculta', 'encryption': 'Abierta', 'signal': ''}
            elif current_bss:
                if line.startswith('SSID:'):
                    essid = line.split('SSID:')[1].strip()
                    if essid and not essid.startswith('\\x00'):
                        networks[current_bss]['essid'] = essid
                elif line.startswith('RSN:') or line.startswith('WPA:'):
                    networks[current_bss]['encryption'] = 'Protegida (WPA/WPA2/WPA3)'
                elif line.startswith('signal:'):
                    networks[current_bss]['signal'] = line.split('signal:')[1].strip()
        
        unique_networks = []
        seen_ssids = set()
        
        for data in networks.values():
            if data['essid'] not in seen_ssids and data['essid'] != 'Oculta':
                unique_networks.append(data)
                seen_ssids.add(data['essid'])
        
        return sorted(unique_networks, key=lambda x: x['essid'])
    
    def connect_to_wifi(self, ssid, password=None, dhcp=True, static_ip=None):
        """Crea y aplica configuración netplan modular para WiFi"""
        print(f"🔗 Configurando conexión a '{ssid}'...")
        
        try:
            # Asegurar que la interfaz esté encendida
            self.run_command(['ip', 'link', 'set', self.interface, 'up'], sudo=True)
            time.sleep(2)
            
            self.backup_netplan_config()
            
            wifi_config = {
                'network': {
                    'version': 2,
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
            
            if static_ip and not dhcp:
                interface_config = wifi_config['network']['wifis'][self.interface]
                interface_config['addresses'] = [static_ip['address']]
                if 'gateway' in static_ip:
                    interface_config['routes'] = [{'to': 'default', 'via': static_ip['gateway']}]
                if 'dns' in static_ip:
                    interface_config['nameservers'] = {'addresses': static_ip['dns']}
            
            with open(self.wifi_config_file, 'w') as f:
                yaml.dump(wifi_config, f, default_flow_style=False)
            
            os.chmod(self.wifi_config_file, 0o600)
            
            return self.apply_netplan_config()
            
        except Exception as e:
            print(f"❌ Error interno configurando WiFi: {e}")
            return False
    
    def apply_netplan_config(self):
        """Genera y aplica la configuración, mostrando errores críticos si falla"""
        try:
            print("🔄 Generando y aplicando configuración netplan...")
            
            result_gen = self.run_command(['netplan', 'generate'], sudo=True, show_errors=True)
            if result_gen is None:
                print("❌ Error crítico en 'netplan generate'.")
                return False
            
            result_app = self.run_command(['netplan', 'apply'], sudo=True, show_errors=True)
            if result_app is None:
                print("❌ Error crítico en 'netplan apply'.")
                return False
            
            print("⏳ Esperando que la conexión se establezca (10s)...")
            time.sleep(10)
            
            return self.check_connection()
            
        except Exception as e:
            print(f"❌ Error general aplicando netplan: {e}")
            return False
    
    def check_connection(self):
        """Verifica el estado de la conexión e IP"""
        interface_status = self.run_command(['ip', 'addr', 'show', self.interface])
        has_ip = False
        
        if interface_status and 'inet ' in interface_status:
            for line in interface_status.split('\n'):
                if 'inet ' in line:
                    ip = line.split()[1]
                    print(f"✅ Dirección IP asignada: {ip}")
                    has_ip = True
                    break
        
        if not has_ip:
            print("❌ Sin dirección IP asignada. Revisa la contraseña o el router.")
            return False
        
        try:
            subprocess.run(['ping', '-c', '3', '-W', '5', '8.8.8.8'], capture_output=True, check=True)
            print("✅ Conexión a Internet activa")
            return True
        except subprocess.CalledProcessError:
            print("⚠️  El equipo tiene IP pero no responde a ping externo (Sin Internet).")
            return True 
    
    def disconnect_wifi(self):
        """Desconecta el WiFi eliminando el archivo modular y apagando la interfaz"""
        print("🔌 Apagando adaptador WiFi...")
        
        try:
            if self.wifi_config_file.exists():
                self.backup_netplan_config()
                self.run_command(['rm', '-f', str(self.wifi_config_file)], sudo=True)
                self.run_command(['netplan', 'apply'], sudo=True)
            
            result = self.run_command(['ip', 'link', 'set', self.interface, 'down'], sudo=True)
            
            if result is not None:
                print(f"✅ Interfaz inalambrica '{self.interface}' APAGADA exitosamente.")
            else:
                print(f"❌ Problema al intentar apagar la interfaz {self.interface}.")
            
        except Exception as e:
            print(f"❌ Error apagando WiFi: {e}")
    
    def list_saved_networks(self):
        print("📋 Redes configuradas temporalmente:")
        if not self.wifi_config_file.exists():
            print("   No hay redes WiFi personalizadas.")
            return
            
        try:
            with open(self.wifi_config_file, 'r') as f:
                config = yaml.safe_load(f)
                
            if config and 'network' in config and 'wifis' in config['network']:
                for interface, settings in config['network']['wifis'].items():
                    if 'access-points' in settings:
                        for ssid in settings['access-points']:
                            print(f"   • {ssid} (Interfaz: {interface})")
        except Exception as e:
            print(f"❌ Error leyendo configuración: {e}")
    
    def get_interface_status(self):
        print(f"📊 Estado de {self.interface}:")
        
        link_info = self.run_command(['iw', 'dev', self.interface, 'link'])
        if link_info and "Not connected" not in link_info:
            for line in link_info.split('\n'):
                line = line.strip()
                if line.startswith('SSID:'):
                    print(f"   Red: {line.split('SSID:')[1].strip()}")
                elif line.startswith('signal:'):
                    print(f"   Señal: {line.split('signal:')[1].strip()}")
        else:
            print("   Red: Desconectado o Apagado")
        
        ip_info = self.run_command(['ip', 'addr', 'show', self.interface])
        if ip_info:
            for line in ip_info.split('\n'):
                if 'inet ' in line:
                    print(f"   IP: {line.strip().split()[1]}")
                elif 'state ' in line:
                    print(f"   Estado Enlace: {line.split('state')[1].split()[0]}")

def main():
    manager = NetplanWiFiManager()
    
    while True:
        print("\n" + "="*50)
        print(f"📡 GESTOR WiFi CON NETPLAN [{manager.interface}]")
        print("="*50)
        print("1. Escanear redes disponibles")
        print("2. Conectar a red WiFi (DHCP)")
        print("3. Conectar a red WiFi (IP estática)")
        print("4. Ver estado de conexión")
        print("5. Listar red configurada")
        print("6. Apagar WiFi")
        print("7. Salir")
        print("-"*50)
        
        choice = input("Selecciona una opción (1-7): ").strip()
        
        if choice == '1':
            networks = manager.scan_wifi_networks()
            if networks:
                print("\n📶 Redes disponibles:")
                for i, network in enumerate(networks, 1):
                    señal = f" [Señal: {network['signal']}]" if network['signal'] else ""
                    print(f"  {i}. {network['essid']} - {network['encryption']}{señal}")
        
        elif choice == '2':
            ssid = input("Nombre de la red (SSID) [Dejar blanco para cancelar]: ").strip()
            if not ssid:
                print("🚫 Operación cancelada.")
                continue
            
            password = None
            while True:
                encryption = input("¿La red tiene contraseña? (s/n) [Dejar blanco para cancelar]: ").strip().lower()
                if not encryption:
                    break
                
                if encryption == 's':
                    password = input("Contraseña: ").strip()
                    break
                elif encryption == 'n':
                    break
                else:
                    print("❌ Por favor, ingresa solo 's' para Sí, o 'n' para No.")
            
            if not encryption:
                print("🚫 Operación cancelada.")
                continue
            
            if manager.connect_to_wifi(ssid, password):
                print(f"✅ Proceso de conexión a {ssid} finalizado.")
            else:
                print(f"❌ Error durante el proceso. Revisa los mensajes de arriba.")
        
        elif choice == '3':
            ssid = input("Nombre de la red (SSID) [Dejar blanco para cancelar]: ").strip()
            if not ssid:
                print("🚫 Operación cancelada.")
                continue
            
            password = None
            while True:
                encryption = input("¿La red tiene contraseña? (s/n) [Dejar blanco para cancelar]: ").strip().lower()
                if not encryption:
                    break
                
                if encryption == 's':
                    password = input("Contraseña: ").strip()
                    break
                elif encryption == 'n':
                    break
                else:
                    print("❌ Por favor, ingresa solo 's' para Sí, o 'n' para No.")
            
            if not encryption:
                print("🚫 Operación cancelada.")
                continue
            
            ip = input("Dirección IP estática (ej: 192.168.1.100/24) [Blanco para cancelar]: ").strip()
            if not ip:
                print("🚫 Operación cancelada.")
                continue
                
            try:
                ipaddress.ip_interface(ip)
            except ValueError:
                print("❌ Formato de IP inválido. Debes incluir /24 u otra máscara.")
                continue

            gateway = input("Gateway o Puerta de Enlace (ej: 192.168.1.1): ").strip()
            dns_input = input("DNS (separados por coma, ej: 8.8.8.8,1.1.1.1): ").strip()
            dns = [d.strip() for d in dns_input.split(',')] if dns_input else []
            
            static_config = {'address': ip, 'gateway': gateway, 'dns': dns}
            if manager.connect_to_wifi(ssid, password, dhcp=False, static_ip=static_config):
                print(f"✅ Proceso estático a {ssid} finalizado.")
            else:
                print(f"❌ Error conectando a {ssid}")
        
        elif choice == '4':
            manager.get_interface_status()
            print("-" * 30)
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
        
        # --- MEJORA: Bucle estricto para Enter ---
        while True:
            tecla = input("\nPresiona Enter para continuar...")
            if tecla == "":
                break
            else:
                print("⚠️  Entrada no válida. Por favor, no escribas nada, solo presiona la tecla Enter.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("🔒 Este script requiere permisos de superusuario (sudo).")
        sys.exit(1)
    
    tools = ['netplan', 'iw', 'ip', 'wpa_supplicant']
    missing_tools = [tool for tool in tools if shutil.which(tool) is None]
    
    if missing_tools:
        print("❌ Faltan herramientas necesarias en el sistema:")
        for tool in missing_tools:
            print(f"  - {tool}")
        print("\nPara instalarlas, ejecuta:")
        print("sudo apt update && sudo apt install netplan.io iw iproute2 wpasupplicant")
        sys.exit(1)
            
    main()