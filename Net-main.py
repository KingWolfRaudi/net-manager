#!/usr/bin/env python3
"""
Gestor de Redes WiFi para Ubuntu Server con Netplan
Optimizado para hardware nativo (Chromebook Standalone)
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
        
    def run_command(self, command, sudo=False):
        """Ejecuta un comando en la terminal"""
        try:
            if sudo:
                command = ['sudo'] + command
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            # Silenciamos el error por consola para mantener limpia la interfaz, 
            # pero retornamos None para manejar el fallo lógicamente.
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
        
        # Si no detecta con 'wl', probar interfaces comunes
        for iface in ['wlan0', 'wlp1s0', 'wlp2s0']:
            try:
                subprocess.run(['ip', 'link', 'show', iface], capture_output=True, check=True)
                return iface
            except:
                continue
        
        return 'wlan0' # Valor por defecto seguro
    
    def backup_netplan_config(self):
        """Crea un backup de la configuración WiFi actual de netplan si existe"""
        if self.wifi_config_file.exists():
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            backup_file = self.backup_dir / f"99-wifi-config_{timestamp}.yaml"
            shutil.copy2(self.wifi_config_file, backup_file)
            print(f"✅ Backup creado: {backup_file}")
    
    def scan_wifi_networks(self):
        """Escanea redes WiFi disponibles usando la herramienta moderna 'iw'"""
        print("📡 Escaneando redes WiFi...")
        
        # Activar interfaz temporalmente para escanear
        self.run_command(['ip', 'link', 'set', self.interface, 'up'], sudo=True)
        time.sleep(2)
        
        # Escanear con iw
        scan_result = self.run_command(['iw', 'dev', self.interface, 'scan'], sudo=True)
        
        if not scan_result:
            print("❌ Error: No se pudo realizar el escaneo o la interfaz está ocupada.")
            return []

        networks = {}
        current_bss = None
        
        for line in scan_result.split('\n'):
            line = line.strip()
            if line.startswith('BSS '):
                # Extraer la MAC del BSS
                current_bss = line.split()[1].split('(')[0]
                networks[current_bss] = {'essid': 'Oculta', 'encryption': 'Abierta', 'signal': ''}
            elif current_bss:
                if line.startswith('SSID:'):
                    essid = line.split('SSID:')[1].strip()
                    # Ignorar los SSID vacíos (ej. '\x00')
                    if essid and not essid.startswith('\\x00'):
                        networks[current_bss]['essid'] = essid
                elif line.startswith('RSN:') or line.startswith('WPA:'):
                    networks[current_bss]['encryption'] = 'Protegida (WPA/WPA2/WPA3)'
                elif line.startswith('signal:'):
                    networks[current_bss]['signal'] = line.split('signal:')[1].strip()
        
        # Filtrar redes únicas para no mostrar duplicados (mismo SSID en distintos canales)
        unique_networks = []
        seen_ssids = set()
        
        for data in networks.values():
            if data['essid'] not in seen_ssids and data['essid'] != 'Oculta':
                unique_networks.append(data)
                seen_ssids.add(data['essid'])
        
        # Ordenar alfabéticamente
        return sorted(unique_networks, key=lambda x: x['essid'])
    
    def connect_to_wifi(self, ssid, password=None, dhcp=True, static_ip=None):
        """Crea y aplica configuración netplan modular para WiFi"""
        print(f"🔗 Configurando conexión a '{ssid}'...")
        
        try:
            # NUEVO: Asegurar que la interfaz esté encendida antes de conectar
            self.run_command(['ip', 'link', 'set', self.interface, 'up'], sudo=True)
            time.sleep(2) # Darle 2 segundos al hardware para despertar
            
            self.backup_netplan_config()
            
            # Configuración base limpia SOLO para WiFi
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
            
            # Configuración estática modernizada (sin gateway4)
            if static_ip and not dhcp:
                interface_config = wifi_config['network']['wifis'][self.interface]
                interface_config['addresses'] = [static_ip['address']]
                
                # Nueva sintaxis de Netplan para rutas por defecto
                if 'gateway' in static_ip:
                    interface_config['routes'] = [
                        {'to': 'default', 'via': static_ip['gateway']}
                    ]
                
                if 'dns' in static_ip:
                    interface_config['nameservers'] = {'addresses': static_ip['dns']}
            
            # Escribir el nuevo archivo de configuración modular
            with open(self.wifi_config_file, 'w') as f:
                yaml.dump(wifi_config, f, default_flow_style=False)
            
            # Asegurar permisos estrictos requeridos por Netplan
            os.chmod(self.wifi_config_file, 0o600)
            print("✅ Configuración netplan guardada modularmente (Permisos 600)")
            
            # Aplicar configuración
            return self.apply_netplan_config()
            
        except Exception as e:
            print(f"❌ Error configurando WiFi: {e}")
            return False
    
    def apply_netplan_config(self):
        """Genera y aplica la configuración de netplan"""
        try:
            print("🔄 Aplicando configuración netplan...")
            
            result_gen = self.run_command(['netplan', 'generate'], sudo=True)
            if result_gen is None:
                print("❌ Error al generar netplan. Revisa la sintaxis del YAML.")
                return False
            
            result_app = self.run_command(['netplan', 'apply'], sudo=True)
            if result_app is None:
                print("❌ Error al aplicar netplan.")
                return False
            
            print("⏳ Esperando que la conexión se establezca (10s)...")
            time.sleep(10)
            
            return self.check_connection()
            
        except Exception as e:
            print(f"❌ Error aplicando netplan: {e}")
            return False
    
    def check_connection(self):
        """Verifica el estado de la conexión e IP"""
        print("🔍 Verificando conexión...")
        
        # Verificar IP
        interface_status = self.run_command(['ip', 'addr', 'show', self.interface])
        has_ip = False
        
        if interface_status and 'inet ' in interface_status:
            for line in interface_status.split('\n'):
                if 'inet ' in line:
                    ip = line.split()[1]
                    print(f"📡 Dirección IP asignada: {ip}")
                    has_ip = True
                    break
        
        if not has_ip:
            print("❌ Sin dirección IP asignada. Revisa la contraseña o el servidor DHCP.")
            return False
        
        # Verificar conectividad a Internet
        try:
            print("🌐 Probando conectividad a Internet...")
            subprocess.run(['ping', '-c', '3', '-W', '5', '8.8.8.8'], 
                         capture_output=True, check=True)
            print("✅ Conexión a Internet activa")
            return True
        except subprocess.CalledProcessError:
            print("⚠️  El equipo tiene IP pero no responde a ping externo (Internet).")
            return True # Retorna True porque la red local sí conectó
    
    def disconnect_wifi(self):
        """Desconecta el WiFi eliminando el archivo modular y apagando la interfaz"""
        print("🔌 Apagando adaptador WiFi...")
        
        try:
            # 1. Eliminar configuración temporal si existe
            if self.wifi_config_file.exists():
                self.backup_netplan_config()
                self.run_command(['rm', '-f', str(self.wifi_config_file)], sudo=True)
                self.run_command(['netplan', 'apply'], sudo=True)
            
            # 2. Apagar la interfaz (Equivalente al switch de apagar WiFi)
            result = self.run_command(['ip', 'link', 'set', self.interface, 'down'], sudo=True)
            
            # Si run_command no devuelve None, significa que se ejecutó bien
            if result is not None:
                print(f"✅ Interfaz inalambrica '{self.interface}' APAGADA exitosamente.")
                print("💡 Nota: El WiFi se encenderá automáticamente la próxima vez que intentes escanear o conectar.")
            else:
                print(f"❌ Hubo un problema al intentar apagar la interfaz {self.interface}.")
            
        except Exception as e:
            print(f"❌ Error apagando WiFi: {e}")
        """Desconecta el WiFi eliminando el archivo modular"""
        print("🔌 Desconectando WiFi...")
        
        try:
            if self.wifi_config_file.exists():
                self.backup_netplan_config()
                self.run_command(['rm', '-f', str(self.wifi_config_file)], sudo=True)
                print(f"✅ Archivo de configuración eliminado: {self.wifi_config_file}")
                
                # Aplicar cambios para soltar la red
                self.run_command(['netplan', 'apply'], sudo=True)
                print("✅ WiFi desconectado exitosamente.")
            else:
                print("⚠️  No hay configuración WiFi activa para desconectar.")
            
        except Exception as e:
            print(f"❌ Error desconectando WiFi: {e}")
    
    def list_saved_networks(self):
        """Lista la red WiFi configurada actualmente en el archivo modular"""
        print("📋 Redes configuradas en netplan:")
        
        if not self.wifi_config_file.exists():
            print("   No hay redes WiFi personalizadas (Archivo 99 no existe).")
            return
            
        try:
            with open(self.wifi_config_file, 'r') as f:
                config = yaml.safe_load(f)
                
            if config and 'network' in config and 'wifis' in config['network']:
                for interface, settings in config['network']['wifis'].items():
                    if 'access-points' in settings:
                        for ssid in settings['access-points']:
                            print(f"   • {ssid} (Interfaz: {interface})")
            else:
                print("   El archivo existe pero no contiene configuraciones de WiFi válidas.")
        except Exception as e:
            print(f"❌ Error leyendo la configuración: {e}")
    
    def get_interface_status(self):
        """Obtiene estado detallado usando herramientas modernas (iw e ip)"""
        print(f"📊 Estado de {self.interface}:")
        
        # Conexión WiFi actual (iw en lugar del viejo iwconfig)
        link_info = self.run_command(['iw', 'dev', self.interface, 'link'])
        if link_info and "Not connected" not in link_info:
            for line in link_info.split('\n'):
                line = line.strip()
                if line.startswith('SSID:'):
                    print(f"   Red: {line.split('SSID:')[1].strip()}")
                elif line.startswith('signal:'):
                    print(f"   Señal: {line.split('signal:')[1].strip()}")
        else:
            print("   Red: Desconectado")
        
        # Información de la interfaz
        ip_info = self.run_command(['ip', 'addr', 'show', self.interface])
        if ip_info:
            for line in ip_info.split('\n'):
                if 'inet ' in line:
                    print(f"   IP: {line.strip().split()[1]}")
                elif 'state ' in line:
                    estado = line.split('state')[1].split()[0]
                    print(f"   Estado Enlace: {estado}")

def main():
    manager = NetplanWiFiManager()
    
    print(f"🌐 Gestor WiFi Netplan - Interfaz: {manager.interface}")
    
    while True:
        print("\n" + "="*50)
        print("📡 GESTOR WiFi CON NETPLAN (Modo Modular)")
        print("="*50)
        print("1. Escanear redes disponibles")
        print("2. Conectar a red WiFi (DHCP)")
        print("3. Conectar a red WiFi (IP estática)")
        print("4. Ver estado de conexión")
        print("5. Listar red configurada")
        print("6. Desconectar WiFi")
        print("7. Salir")
        print("-"*50)
        
        choice = input("Selecciona una opción (1-7): ").strip()
        
        if choice == '1':
            networks = manager.scan_wifi_networks()
            if networks:
                print("\n📶 Redes disponibles (Únicas):")
                for i, network in enumerate(networks, 1):
                    señal = f" [Señal: {network['signal']}]" if network['signal'] else ""
                    print(f"  {i}. {network['essid']} - {network['encryption']}{señal}")
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
                print(f"✅ Proceso de conexión a {ssid} finalizado.")
            else:
                print(f"❌ Error durante el proceso de conexión a {ssid}.")
        
        elif choice == '3':
            ssid = input("Nombre de la red (SSID): ").strip()
            if not ssid:
                print("❌ El SSID no puede estar vacío")
                continue
            
            password = None
            encryption = input("¿La red tiene contraseña? (s/n): ").strip().lower()
            if encryption == 's':
                password = input("Contraseña: ").strip()
            
            # Validación de IP usando la librería ipaddress
            ip = input("Dirección IP estática (ej: 192.168.1.100/24): ").strip()
            try:
                ipaddress.ip_interface(ip)
            except ValueError:
                print("❌ Formato de IP inválido. Asegúrate de incluir la máscara (ej: /24)")
                continue

            gateway = input("Gateway o Puerta de Enlace (ej: 192.168.1.1): ").strip()
            dns_input = input("DNS (separados por coma, ej: 8.8.8.8,1.1.1.1): ").strip()
            dns = [d.strip() for d in dns_input.split(',')] if dns_input else []
            
            static_config = {
                'address': ip,
                'gateway': gateway,
                'dns': dns
            }
            
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
        
        input("\nPresiona Enter para continuar...")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("🔒 Este script requiere permisos de superusuario")
        print("Ejecuta: sudo python3 netplan_wifi_manager.py")
        sys.exit(1)
    
    # Verificar que las herramientas necesarias están disponibles
    tools = ['netplan', 'iw', 'ip']
    for tool in tools:
        if shutil.which(tool) is None:
            print(f"❌ La herramienta '{tool}' no está instalada.")
            print(f"Instálala o verifica tu sistema Ubuntu Server.")
            sys.exit(1)
            
    main()