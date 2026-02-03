from datetime import datetime, timedelta
import os
import logging
import random


log = logging.getLogger("NF-ESN")

def chrome_esn_generator():

    ESN_GEN = "".join(random.choice("0123456789ABCDEF") for _ in range(30))
    esn_file = '.esn'
    
    def gen_file():
        with open(esn_file, 'w') as file:
            file.write(f'NFCDIE-03-{ESN_GEN}')
    
    if not os.path.isfile(esn_file):
        log.warning("Generating a new Chrome ESN")
        gen_file()
    
    file_datetime = datetime.fromtimestamp(os.path.getmtime(esn_file))
    time_diff = datetime.now() - file_datetime
    if time_diff > timedelta(hours=6):
        log.warning("Old ESN detected, Generating a new Chrome ESN")
        gen_file()

    with open(esn_file, 'r') as f:
        esn =  f.read()

    return esn

def edge_esn_generator():

    ESN_GEN = "".join(random.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(24))
    esn_file = '.esn'
    
    def gen_file():
        with open(esn_file, 'w') as file:
            file.write(f'NFCDIE-03-{ESN_GEN}1111')
    
    if not os.path.isfile(esn_file):
        log.warning("Generating a new Edge ESN")
        gen_file()
    
    file_datetime = datetime.fromtimestamp(os.path.getmtime(esn_file))
    time_diff = datetime.now() - file_datetime
    if time_diff > timedelta(hours=6):
        log.warning("Old ESN detected, Generating a new Edge ESN")
        gen_file()

    with open(esn_file, 'r') as f:
        esn =  f.read()

    return esn


def playready_esn_generator():
    # Lista di modelli di TV e dispositivi PlayReady
    tv_models = [
        "HE55A7000EUWTS",  # Hisense
        "KD55X85J",        # Sony
        "UN55TU7000",      # Samsung
        "OLED55C1",        # LG
        "55PUS7805",       # Philips
        "55R635",          # TCL
        "L55M5-Z2",        # Xiaomi
    ]
    
    # Lista di produttori
    manufacturers = [
        "HISENSE",
        "SONY",
        "SAMSUNG",
        "LG",
        "PHILIPS",
        "TCL",
        "XIAOMI"
    ]
    
    # Scegli un produttore e un modello casualmente
    manufacturer = random.choice(manufacturers)
    model = random.choice(tv_models)
    
    esn_file = '.esn_playready'
    
    def gen_file():
        # Crea un ESN nel formato NFANDROID1-PRN-[MANUFACTURER]-[MODEL]
        esn = f"NFANDROID1-PRN-{manufacturer}-{model}"
        with open(esn_file, 'w') as file:
            file.write(esn)
    
    if not os.path.isfile(esn_file):
        log.warning("Generating a new PlayReady ESN")
        gen_file()
    
    file_datetime = datetime.fromtimestamp(os.path.getmtime(esn_file))
    time_diff = datetime.now() - file_datetime
    if time_diff > timedelta(hours=6):
        log.warning("Old ESN detected, Generating a new PlayReady ESN")
        gen_file()

    with open(esn_file, 'r') as f:
        esn = f.read()

    return esn

def android_esn_generator():
    # Parametri per dispositivi Android
    manufacturers = ["SAMSUNG", "ONEPLUS", "XIAOMI", "MOTOROLA", "GOOGLE", "NVIDIA"]
    models = [
        "SM-T865", "SM-G975F", "SM-N975F",   # Samsung
        "IN2020", "KB2000", "LE2100",        # OnePlus
        "M2007J3SG", "M2004J19C", "M2102J20SG",  # Xiaomi
        "Pixel 5", "Pixel 6 Pro", "Pixel 7",     # Google
        "SHIELD Android TV", "SHIELD Pro"        # NVIDIA
    ]
    
    # Genera una stringa casuale alfanumerica per l'ID del dispositivo
    device_id = "".join(random.choice("0123456789ABCDEF") for _ in range(16))
    
    esn_file = '.esn_android'
    
    def gen_file():
        manufacturer = random.choice(manufacturers)
        model = random.choice(models)
        # Formato ESN per Android: NFANDROID1-PRV-[build info]-[device ID]-[model]
        esn = f"NFANDROID1-PRV-{manufacturer[:4]}{random.randint(1000,9999)}-{device_id}-{model}"
        with open(esn_file, 'w') as file:
            file.write(esn)
    
    if not os.path.isfile(esn_file):
        log.warning("Generating a new Android ESN")
        gen_file()
    
    file_datetime = datetime.fromtimestamp(os.path.getmtime(esn_file))
    time_diff = datetime.now() - file_datetime
    if time_diff > timedelta(hours=6):
        log.warning("Old ESN detected, Generating a new Android ESN")
        gen_file()

    with open(esn_file, 'r') as f:
        esn = f.read()

    return esn
