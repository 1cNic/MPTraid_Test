import xml.etree.ElementTree as ET
import os
import sys
import re

# Путь к корню проекта (автоматически определяется относительно скрипта)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == 'tools' else SCRIPT_DIR

# Папки с метаданными
MD_FOLDERS = ['Catalogs', 'Documents', 'AccumulationRegisters', 'InformationRegisters', 
              'ChartsOfCharacteristicTypes', 'ChartsOfCalculationTypes', 'Enums', 
              'CommonModules', 'Reports', 'DataProcessors']

# Namespace для парсинга
NS = {'md': 'http://v8.1c.ru/8.3/MDClasses', 
      'xr': 'http://v8.1c.ru/8.3/xcf/readable',
      'v8': 'http://v8.1c.ru/8.1/data/core',
      'xsi': 'http://www.w3.org/2001/XMLSchema-instance'}

# Regex для UUID
UUID_REGEX = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# Маппинг тегов Configuration.xml на папки и префиксы типов
TAG_TO_FOLDER = {
    'Catalog': ('Catalogs', 'CatalogRef'),
    'Document': ('Documents', 'DocumentRef'),
    'AccumulationRegister': ('AccumulationRegisters', 'AccumulationRegisterRef'),
    'InformationRegister': ('InformationRegisters', 'InformationRegisterRef'),
    'ChartOfCharacteristicTypes': ('ChartsOfCharacteristicTypes', 'ChartOfCharacteristicTypesRef'),
    'ChartOfCalculationTypes': ('ChartsOfCalculationTypes', 'ChartOfCalculationTypesRef'),
    'Enum': ('Enums', 'EnumRef'),
    'CommonModule': ('CommonModules', None),
    'Report': ('Reports', 'ReportRef'),
    'DataProcessor': ('DataProcessors', 'DataProcessorRef'),
}

def get_element_text(element, tag, namespace=NS):
    """Безопасное получение текста элемента"""
    try:
        el = element.find(f'md:{tag}', namespace)
        if el is None:
            el = element.find(tag)
        return el.text.strip() if el is not None and el.text else None
    except:
        return None

def validate_uuid(elem, filepath, errors):
    """Проверка формата UUID во всем файле"""
    for attr_name, attr_value in elem.attrib.items():
        if attr_name == 'uuid':
            if not UUID_REGEX.match(attr_value):
                errors.append(f"Неверный формат UUID: {attr_value}")
    for child in elem:
        validate_uuid(child, filepath, errors)

def validate_catalog(elem, filepath):
    errors = []
    ic_prop = elem.find('.//md:IncludeInCommandInterface', NS)
    if ic_prop is not None:
        errors.append("39.20: Свойство 'IncludeInCommandInterface' не поддерживается для Catalog. Удалите его.")
    predefined_in_main = elem.find('.//md:PredefinedItem', NS)
    if predefined_in_main is not None:
        errors.append("39.14: 'PredefinedItem' найден в основном XML. Перенесите в 'Ext/Predefined.xml'.")
    return errors

def validate_chart_of_characteristic_types(elem, filepath):
    errors = []
    internal_info = elem.find('md:InternalInfo', NS)
    if internal_info is not None:
        gen_types = internal_info.findall('xr:GeneratedType', NS)
        has_characteristic = False
        for gt in gen_types:
            category = gt.get('category')
            if category == 'Characteristic':
                has_characteristic = True
                break
        if not has_characteristic:
            errors.append("39.9: В 'InternalInfo' отсутствует тип с category='Characteristic'.")
    else:
        errors.append("Отсутствует 'InternalInfo'.")

    forbidden_props = ['CodeType', 'CharacteristicType', 'Owners'] 
    props = elem.find('md:Properties', NS)
    if props is not None:
        for prop in props:
            tag = prop.tag.split('}')[-1]
            if tag in forbidden_props:
                errors.append(f"39.10: Свойство '{tag}' не поддерживается для ChartOfCharacteristicTypes. Удалите его.")
            if tag == 'CodeSeries' and prop.text and 'WholeCatalog' in (prop.text or ''):
                 errors.append("39.10: Неверное значение 'WholeCatalog' для 'CodeSeries'. Используйте 'WholeCharacteristicKind'.")

    if elem.find('md:ChildObjects', NS) is None:
        errors.append("39.11: Отсутствует узел 'ChildObjects'. Добавьте пустой '<ChildObjects/>'.")
        
    predefined_in_main = elem.find('.//md:PredefinedItem', NS)
    if predefined_in_main is not None:
        errors.append("39.14: 'PredefinedItem' найден в основном XML. Перенесите в 'Ext/Predefined.xml'.")

    return errors

def validate_object_metadata(filepath, root_dir):
    """Общие проверки для любого объекта метаданных"""
    errors = []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        root_tag = root.tag.split('}')[-1]
        validate_uuid(root, filepath, errors)
        if root_tag == 'Catalog':
            errors.extend(validate_catalog(root, filepath))
        elif root_tag == 'ChartOfCharacteristicTypes':
            errors.extend(validate_chart_of_characteristic_types(root, filepath))
    except ET.ParseError as e:
        errors.append(f"Ошибка парсинга XML: {e}")
    return errors

def check_forms_references(folder, filename, root_dir):
    """Проверка ссылок на формы: есть ли в XML форма, а физически папки нет"""
    errors = []
    filepath = os.path.join(folder, filename)
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        child_objects = root.find('md:ChildObjects', NS)
        if child_objects is not None:
            for form_elem in child_objects.findall('md:Form', NS):
                if form_elem.text:
                    form_name = form_elem.text.strip()
                    base_folder = os.path.splitext(filename)[0]
                    form_folder = os.path.join(folder, base_folder, 'Forms', form_name)
                    if not os.path.exists(form_folder):
                        errors.append(f"Ссылка на форму '{form_name}' есть в XML, но папка '{form_folder}' отсутствует.")
    except Exception as e:
        errors.append(f"Ошибка при проверке форм: {e}")
    return errors

def check_config_synchronization(root_dir):
    """Сверка списка объектов в Configuration.xml с реальными файлами"""
    errors = []
    config_path = os.path.join(root_dir, 'Configuration.xml')
    if not os.path.exists(config_path):
        return errors
        
    try:
        tree = ET.parse(config_path)
        root = tree.getroot()
        
        # Robust search for ChildObjects anywhere in the tree
        child_objects = None
        for elem in root.iter():
            if elem.tag.endswith('ChildObjects'):
                child_objects = elem
                break
        
        config_objects = {}
        if child_objects is not None:
            for child in child_objects:
                tag = child.tag.split('}')[-1]
                if tag in TAG_TO_FOLDER:
                    folder_name = TAG_TO_FOLDER[tag][0]
                    if folder_name not in config_objects:
                        config_objects[folder_name] = []
                    config_objects[folder_name].append(child.text.strip() if child.text else '')
        
        for folder in MD_FOLDERS:
            folder_path = os.path.join(root_dir, folder)
            if not os.path.exists(folder_path):
                if folder in config_objects:
                    errors.append(f"Синхронизация: В Configuration.xml есть объекты типа '{folder}', но папка отсутствует.")
                continue
                
            real_objects = []
            for f in os.listdir(folder_path):
                if f.endswith('.xml'):
                    real_objects.append(os.path.splitext(f)[0])
            
            expected = config_objects.get(folder, [])
            missing_in_config = set(real_objects) - set(expected)
            missing_in_fs = set(expected) - set(real_objects)
            
            if missing_in_config:
                errors.append(f"Синхронизация ({folder}): Файлы {missing_in_config} существуют, но не прописаны в Configuration.xml")
            if missing_in_fs:
                errors.append(f"Синхронизация ({folder}): Объекты {missing_in_fs} прописаны в Configuration.xml, но файлы отсутствуют")

    except Exception as e:
        errors.append(f"Ошибка проверки Configuration.xml: {e}")
    return errors

def get_all_metadata_objects(root_dir):
    """Собирает словарь всех существующих объектов метаданных: {'Номенклатура': 'Catalogs', ...}"""
    objects = {}
    for folder in MD_FOLDERS:
        folder_path = os.path.join(root_dir, folder)
        if os.path.exists(folder_path):
            for f in os.listdir(folder_path):
                if f.endswith('.xml'):
                    name = os.path.splitext(f)[0]
                    objects[name] = folder
    return objects

def check_metadata_references(root_dir):
    """Проверка битых ссылок на объекты метаданных в типах реквизитов"""
    errors = []
    existing_objects = get_all_metadata_objects(root_dir)
    ref_pattern = re.compile(r'cfg:(\w+Ref)\.(\w+)')
    
    for folder in MD_FOLDERS:
        folder_path = os.path.join(root_dir, folder)
        if not os.path.exists(folder_path):
            continue
            
        for filename in os.listdir(folder_path):
            if not filename.endswith('.xml'):
                continue
                
            filepath = os.path.join(folder_path, filename)
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()
                for type_elem in root.iter('{http://v8.1c.ru/8.1/data/core}Type'):
                    if type_elem.text:
                        matches = ref_pattern.findall(type_elem.text)
                        for ref_prefix, obj_name in matches:
                            if obj_name not in existing_objects:
                                if not obj_name.startswith('Standard') and not obj_name.startswith('Common'):
                                    errors.append(f"{os.path.relpath(filepath, root_dir)}: Битая ссылка на '{obj_name}' (тип {ref_prefix}). Объект не найден в конфигурации.")
            except Exception:
                pass
    return errors

def main():
    print(f"--- Валидация XML метаданных 1С ---")
    print(f"Корень проекта: {ROOT_DIR}")
    
    total_errors = 0
    files_checked = 0
    
    # 1. Проверка синхронизации с конфигурацией
    sync_errors = check_config_synchronization(ROOT_DIR)
    if sync_errors:
        print("\n[ОШИБКИ СИНХРОНИЗАЦИИ]")
        for err in sync_errors:
            print(f"  - {err}")
        total_errors += len(sync_errors)

    # 2. Проверка битых ссылок
    ref_errors = check_metadata_references(ROOT_DIR)
    if ref_errors:
        print("\n[ОШИБКИ ССЫЛОК]")
        for err in ref_errors:
            print(f"  - {err}")
        total_errors += len(ref_errors)

    # 3. Проверка отдельных файлов
    for folder in MD_FOLDERS:
        folder_path = os.path.join(ROOT_DIR, folder)
        if not os.path.exists(folder_path):
            continue
            
        for filename in os.listdir(folder_path):
            if not filename.endswith('.xml'):
                continue
                
            filepath = os.path.join(folder_path, filename)
            files_checked += 1
            
            file_errors = validate_object_metadata(filepath, ROOT_DIR)
            form_errors = check_forms_references(folder_path, filename, ROOT_DIR)
            
            all_errors = file_errors + form_errors
            
            if all_errors:
                print(f"\n[ОШИБКИ] {os.path.relpath(filepath, ROOT_DIR)}")
                for err in all_errors:
                    print(f"  - {err}")
                total_errors += len(all_errors)

    print(f"\n--- Итог ---")
    print(f"Проверено файлов: {files_checked}")
    if total_errors == 0:
        print("Ошибок не найдено. Конфигурация валидна.")
    else:
        print(f"Найдено ошибок: {total_errors}")
        
    return total_errors

if __name__ == '__main__':
    sys.exit(main())
