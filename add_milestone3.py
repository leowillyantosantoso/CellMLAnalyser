import os
import libcellml
import requests
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from rdflib import Graph

PMR_WORKSPACE_DIR = os.path.expanduser("~/Downloads/modelCE")
BASELINE_UNITS_INPUT = "baseline_units.cellml"
BASELINE_UNITS_OUTPUT = "baseline_units_new.cellml"
RDF_OPB_URL = "https://raw.githubusercontent.com/nickerso/cellml-to-fc/main/rdf_unit_cellml.ttl"
RDF_OPB_LOCAL = "rdf_unit_cellml.ttl"

SI_BASE_UNITS_OPB = {
    "ampere": "OPB_00318",    # Electric current
    "kelvin": "OPB_00293",    # Temperature
    "kilogram": "OPB_01226",  # Mass
    "metre": "OPB_00269",     # Length (British spelling)
    "mole": "OPB_00425",      # Amount of substance
    "second": "OPB_00402",    # Time
}

# ============================================================================
# UNIT BREAKDOWN FUNCTIONS - SIMPLIFIED
# ============================================================================

def parse_cellml_units(file_path):
    """Parse CellML file and extract units definitions."""
    tree = ET.parse(file_path)
    root = tree.getroot()
    
    # Define namespace
    ns = {'cellml': 'http://www.cellml.org/cellml/1.1#'}
    
    units_dict = {}
    
    # Find all units elements
    for units_elem in root.findall('.//cellml:units', ns):
        name = units_elem.get('name')
        if not name:
            continue
            
        components = []
        
        # Parse unit components
        for unit_elem in units_elem.findall('cellml:unit', ns):
            unit_name = unit_elem.get('units')
            if not unit_name:
                continue
                
            exponent = float(unit_elem.get('exponent', '1'))
            multiplier = float(unit_elem.get('multiplier', '1'))
            prefix = unit_elem.get('prefix', '')
            
            components.append({
                'unit': unit_name,
                'exponent': exponent,
                'multiplier': multiplier,
                'prefix': prefix
            })
        
        units_dict[name] = {
            'components': components,
            'element': units_elem  # Keep the original element
        }
    
    return units_dict

def break_down_unit_recursive(unit_name, units_dict, visited=None):
    """Recursively break down a unit into base components."""
    if visited is None:
        visited = set()
    
    # Prevent infinite recursion
    if unit_name in visited:
        return []
    
    visited.add(unit_name)
    
    # If it's a base unit, return it directly
    if unit_name not in units_dict:
        return [{
            'unit': unit_name,
            'exponent': 1.0,
            'multiplier': 1.0,
            'prefix': ''
        }]
    
    unit_def = units_dict[unit_name]
    result = []
    
    for component in unit_def['components']:
        sub_unit = component['unit']
        component_exponent = component['exponent']
        component_multiplier = component['multiplier']
        component_prefix = component['prefix']
        
        # Recursively break down
        sub_components = break_down_unit_recursive(sub_unit, units_dict, visited.copy())
        
        for sub_comp in sub_components:
            # Combine exponents
            new_exponent = sub_comp['exponent'] * component_exponent
            
            # Combine multipliers
            new_multiplier = sub_comp['multiplier'] * component_multiplier
            
            # Handle prefixes - for now just track them
            new_prefix = component_prefix if component_prefix else sub_comp['prefix']
            
            # Find and combine with existing component
            found = False
            for res in result:
                if res['unit'] == sub_comp['unit']:
                    res['exponent'] += new_exponent
                    res['multiplier'] *= new_multiplier
                    # Don't combine prefixes
                    found = True
                    break
            
            if not found:
                result.append({
                    'unit': sub_comp['unit'],
                    'exponent': new_exponent,
                    'multiplier': new_multiplier,
                    'prefix': new_prefix
                })
    
    return result

def create_expanded_cellml_file():
    """Create a new CellML file with all units expanded to base components."""
    print("Breaking down composite units...")
    
    # Check if input file exists
    if not os.path.exists(BASELINE_UNITS_INPUT):
        print(f"Error: Input file '{BASELINE_UNITS_INPUT}' not found.")
        return False
    
    try:
        # Parse the original file
        original_units = parse_cellml_units(BASELINE_UNITS_INPUT)
        
        print(f"Found {len(original_units)} units in {BASELINE_UNITS_INPUT}")
        
        # Create new XML root
        root = ET.Element('model')
        root.set('name', 'baseline_units')
        root.set('xmlns', 'http://www.cellml.org/cellml/1.1#')
        root.set('xmlns:cellml', 'http://www.cellml.org/cellml/1.1#')
        root.set('xmlns:cmeta', 'http://www.cellml.org/metadata/1.0#')
        
        # Process each unit
        expanded_count = 0
        
        for unit_name, unit_def in original_units.items():
            components = unit_def['components']
            
            # Check if this unit is already a base unit (no components or references other units)
            is_simple = len(components) == 1 and components[0]['multiplier'] == 1.0
            
            if is_simple:
                # Copy original unit as-is
                root.append(unit_def['element'])
            else:
                # Break down the unit
                broken_down = break_down_unit_recursive(unit_name, original_units)
                
                # Create new unit element
                units_elem = ET.SubElement(root, 'units')
                units_elem.set('name', unit_name)
                if 'cmeta:id' in unit_def['element'].attrib:
                    units_elem.set('cmeta:id', unit_def['element'].attrib['cmeta:id'])
                
                for comp in broken_down:
                    # Skip components with zero exponent
                    if comp['exponent'] == 0:
                        continue
                    
                    unit_elem = ET.SubElement(units_elem, 'unit')
                    unit_elem.set('units', comp['unit'])
                    
                    if comp['exponent'] != 1.0:
                        unit_elem.set('exponent', str(comp['exponent']))
                    
                    if comp['multiplier'] != 1.0:
                        unit_elem.set('multiplier', str(comp['multiplier']))
                    
                    if comp['prefix']:
                        unit_elem.set('prefix', comp['prefix'])
                
                expanded_count += 1
                
                # Show the expansion
                if len(broken_down) > 1:
                    print(f"  {unit_name}:")
                    for comp in broken_down:
                        prefix_str = f"{comp['prefix']}" if comp['prefix'] else ""
                        exp_str = f"^{comp['exponent']}" if comp['exponent'] != 1.0 else ""
                        mult_str = f" * {comp['multiplier']}" if comp['multiplier'] != 1.0 else ""
                        print(f"    {prefix_str}{comp['unit']}{exp_str}{mult_str}")
        
        print(f"Expanded {expanded_count} composite units")
        
        # Convert to string with proper formatting
        xml_str = ET.tostring(root, encoding='unicode')
        
        # Pretty format
        import re
        xml_str = re.sub(r'><', '>\n<', xml_str)
        xml_str = re.sub(r'(<units[^>]*>)', r'\n  \1', xml_str)
        xml_str = re.sub(r'(<unit[^>]*/>)', r'    \1', xml_str)
        xml_str = re.sub(r'(</units>)', r'  \1', xml_str)
        
        # Add XML declaration
        xml_str = '<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n' + xml_str
        
        # Save to file
        with open(BASELINE_UNITS_OUTPUT, 'w', encoding='utf-8') as f:
            f.write(xml_str)
        
        print(f"✓ Created {BASELINE_UNITS_OUTPUT}")
        return True
        
    except Exception as e:
        print(f"✗ Error breaking down units: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# ORIGINAL MAIN PROGRAM FUNCTIONS
# ============================================================================

def download_file(url, local_path):
    if not os.path.exists(local_path):
        r = requests.get(url)
        r.raise_for_status()
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(r.text)

def find_cellml_files(root_dir):
    cellml_files = []
    for dirpath, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".cellml"):
                cellml_files.append(os.path.join(dirpath, file))
    return cellml_files

def parse_baseline_units():
    """Parse baseline units from the expanded file."""
    # Try to use the expanded file first
    if not os.path.exists(BASELINE_UNITS_OUTPUT):
        print(f"Warning: {BASELINE_UNITS_OUTPUT} not found.")
        if os.path.exists(BASELINE_UNITS_INPUT):
            print(f"Using {BASELINE_UNITS_INPUT} instead.")
            baseline_file = BASELINE_UNITS_INPUT
        else:
            print("No baseline units file found.")
            return {}
    else:
        baseline_file = BASELINE_UNITS_OUTPUT
    
    parser = libcellml.Parser()
    parser.setStrict(False)
    
    try:
        with open(baseline_file, "r", encoding="utf-8") as f:
            baseline_content = f.read()
        
        baseline_model = parser.parseModel(baseline_content)
        if not baseline_model:
            print("  Failed to parse baseline model")
            return {}
        
        baseline_units = {}
        for i in range(baseline_model.unitsCount()):
            units = baseline_model.units(i)
            baseline_units[units.name()] = units
        
        print(f"  Loaded {len(baseline_units)} units from {baseline_file}")
        return baseline_units
        
    except Exception as e:
        print(f"  Error parsing baseline units: {e}")
        return {}

def load_opb_mappings(rdf_file_path=RDF_OPB_LOCAL):
    download_file(RDF_OPB_URL, rdf_file_path)
    opb_map = {}
    with open(rdf_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("@prefix"):
                continue
            if "is_unit_of:" in line and "opb:OPB_" in line:
                parts = line.split()
                if parts[0].startswith("ex:"):
                    unit_name = parts[0][3:]
                    opb_codes = []
                    opb_part = line.split("is_unit_of:")[1]
                    for code in opb_part.split(","):
                        code = code.strip().replace("opb:OPB_", "OPB_").replace(".", "").replace(";", "")
                        if code.startswith("OPB_"):
                            opb_codes.append(code)
                    opb_map[unit_name] = opb_codes
    return opb_map

def resolve_imports(model, base_path):
    importer = libcellml.Importer()
    importer.resolveImports(model, base_path)
    return importer

def validate_model(model):
    validator = libcellml.Validator()
    validator.validateModel(model)
    return validator.errorCount() == 0
def map_variable_units_to_opb(model, baseline_units, opb_map):
    mapped = 0
    total = 0
    mapping_details = []
    unmapped_details = []
    model_unit_names = [model.units(i).name() for i in range(model.unitsCount())]
    print(f"    Components: {model.componentCount()}")
    
    for i in range(model.componentCount()):
        comp = model.component(i)
        print(f"      Component '{comp.name()}': {comp.variableCount()} variables")
        
        for j in range(comp.variableCount()):
            var = comp.variable(j)
            unit_obj = var.units()
            
            if hasattr(unit_obj, "name"):
                unit_name = unit_obj.name()
            else:
                unit_name = str(unit_obj) if unit_obj else "dimensionless"
            
            print(f"        Variable '{var.name()}' unit: '{unit_name}'")
            
            # Handle dimensionless units - try to find a compatible baseline unit
            if unit_name == "dimensionless" or not unit_obj:
                total += 1
                
                # Try to find a compatible baseline unit for dimensionless
                # Create a simple dimensionless units object for compatibility checking
                try:
                    dimensionless_unit = libcellml.Units("dimensionless")
                    
                    # Check compatibility with baseline units that might represent dimensionless
                    mapped_this = False
                    for base_name, base_units in baseline_units.items():
                        try:
                            if libcellml.Units.compatible(dimensionless_unit, base_units):
                                opb_codes = opb_map.get(base_name)
                                mapping_details.append({
                                    "variable": var.name(),
                                    "unit": "dimensionless",
                                    "mapped_to": base_name,
                                    "opb_code": opb_codes
                                })
                                mapped += 1
                                mapped_this = True
                                print(f"          ✓ Dimensionless -> '{base_name}'")
                                break
                        except:
                            continue
                    
                    if not mapped_this:
                        # If no compatible baseline unit found, still count as mapped but without OPB
                        mapping_details.append({
                            "variable": var.name(),
                            "unit": "dimensionless",
                            "mapped_to": "dimensionless",
                            "opb_code": None
                        })
                        mapped += 1
                        print(f"          ✓ Dimensionless (no OPB mapping)")
                        
                except Exception as e:
                    # Fallback if we can't create the units object
                    mapping_details.append({
                        "variable": var.name(),
                        "unit": "dimensionless",
                        "mapped_to": "dimensionless",
                        "opb_code": None
                    })
                    mapped += 1
                    total += 1
                    print(f"          ✓ Dimensionless (fallback)")
                
                continue
            
            # Check for SI base units first
            if unit_name in SI_BASE_UNITS_OPB:
                opb_code = SI_BASE_UNITS_OPB[unit_name]
                mapping_details.append({
                    "variable": var.name(),
                    "unit": unit_name,
                    "mapped_to": unit_name,
                    "opb_code": [opb_code]
                })
                mapped += 1
                total += 1
                print(f"          ✓ SI base unit -> {opb_code}")
                continue
            
            # Find the units object
            units_obj = None
            if unit_name in model_unit_names:
                for idx in range(model.unitsCount()):
                    if model.units(idx).name() == unit_name:
                        units_obj = model.units(idx)
                        break
            elif unit_name in baseline_units:
                units_obj = baseline_units[unit_name]
            
            if not units_obj:
                unmapped_details.append({
                    "variable": var.name(),
                    "unit": unit_name,
                    "reason": "Unit not found"
                })
                total += 1
                print(f"          ✗ Unit not found")
                continue
            
            total += 1
            mapped_this = False
            
            # Check compatibility with baseline units
            for base_name, base_units in baseline_units.items():
                try:
                    if libcellml.Units.compatible(units_obj, base_units):
                        opb_codes = opb_map.get(base_name)
                        mapping_details.append({
                            "variable": var.name(),
                            "unit": unit_name,
                            "mapped_to": base_name,
                            "opb_code": opb_codes
                        })
                        mapped += 1
                        mapped_this = True
                        print(f"          ✓ Compatible with '{base_name}'")
                        break
                except:
                    continue
            
            if not mapped_this:
                unmapped_details.append({
                    "variable": var.name(),
                    "unit": unit_name,
                    "reason": "No compatible baseline unit found"
                })
                print(f"          ✗ No compatible unit")
    
    return mapped, total, mapping_details, unmapped_details

# def map_variable_units_to_opb(model, baseline_units, opb_map):
#     mapped = 0
#     total = 0
#     mapping_details = []
#     unmapped_details = []
#     model_unit_names = [model.units(i).name() for i in range(model.unitsCount())]
#     print(f"    Components: {model.componentCount()}")
    
#     for i in range(model.componentCount()):
#         comp = model.component(i)
#         print(f"      Component '{comp.name()}': {comp.variableCount()} variables")
        
#         for j in range(comp.variableCount()):
#             var = comp.variable(j)
#             unit_obj = var.units()
            
#             if hasattr(unit_obj, "name"):
#                 unit_name = unit_obj.name()
#             else:
#                 unit_name = str(unit_obj) if unit_obj else "dimensionless"
            
#             print(f"        Variable '{var.name()}' unit: '{unit_name}'")
            
#             # Handle dimensionless units
#             if unit_name == "dimensionless" or not unit_obj:
#                 mapping_details.append({
#                     "variable": var.name(),
#                     "unit": "dimensionless",
#                     "mapped_to": "dimensionless",
#                     "opb_code": None  # No OPB code for dimensionless
#                 })
#                 mapped += 1
#                 total += 1
#                 print(f"          ✓ Dimensionless variable")
#                 continue
            
#             # Check for SI base units first
#             if unit_name in SI_BASE_UNITS_OPB:
#                 opb_code = SI_BASE_UNITS_OPB[unit_name]
#                 mapping_details.append({
#                     "variable": var.name(),
#                     "unit": unit_name,
#                     "mapped_to": unit_name,
#                     "opb_code": [opb_code]
#                 })
#                 mapped += 1
#                 total += 1
#                 print(f"          ✓ SI base unit -> {opb_code}")
#                 continue
            
#             # Find the units object
#             units_obj = None
#             if unit_name in model_unit_names:
#                 for idx in range(model.unitsCount()):
#                     if model.units(idx).name() == unit_name:
#                         units_obj = model.units(idx)
#                         break
#             elif unit_name in baseline_units:
#                 units_obj = baseline_units[unit_name]
            
#             if not units_obj:
#                 unmapped_details.append({
#                     "variable": var.name(),
#                     "unit": unit_name,
#                     "reason": "Unit not found"
#                 })
#                 total += 1
#                 print(f"          ✗ Unit not found")
#                 continue
            
#             total += 1
#             mapped_this = False
            
#             # Check compatibility with baseline units
#             for base_name, base_units in baseline_units.items():
#                 try:
#                     if libcellml.Units.compatible(units_obj, base_units):
#                         opb_codes = opb_map.get(base_name)
#                         mapping_details.append({
#                             "variable": var.name(),
#                             "unit": unit_name,
#                             "mapped_to": base_name,
#                             "opb_code": opb_codes
#                         })
#                         mapped += 1
#                         mapped_this = True
#                         print(f"          ✓ Compatible with '{base_name}'")
#                         break
#                 except:
#                     continue
            
#             if not mapped_this:
#                 unmapped_details.append({
#                     "variable": var.name(),
#                     "unit": unit_name,
#                     "reason": "No compatible baseline unit found"
#                 })
#                 print(f"          ✗ No compatible unit")
    
#     return mapped, total, mapping_details, unmapped_details

def main():
    print("=" * 60)
    print("CELLML UNIT MAPPING TO OPB CODES")
    print("=" * 60)
    
    # Step 1: Create expanded baseline units
    create_expanded_cellml_file()
    
    # Continue with original program
    print("\nScanning for CellML files...")
    cellml_files = find_cellml_files(PMR_WORKSPACE_DIR)
    print(f"Found {len(cellml_files)} CellML files.")
    
    print("Loading baseline units...")
    baseline_units = parse_baseline_units()
    
    print("Loading OPB mappings from RDF...")
    opb_map = load_opb_mappings()
    
    stats = []
    for idx, cellml_path in enumerate(cellml_files, 1):
        print(f"\n[{idx}/{len(cellml_files)}] Processing: {cellml_path}")
        parser = libcellml.Parser()
        parser.setStrict(False)
        with open(cellml_path, "r", encoding="utf-8") as f:
            content = f.read()
        model = parser.parseModel(content)
        if not model:
            print("  Failed to parse model.")
            continue
        
        # Resolve imports
        base_path = os.path.dirname(cellml_path)
        resolve_imports(model, base_path)
        
        # Validate model
        valid = validate_model(model)
        print(f"  Model valid: {valid}")
        
        # Map variable units to OPB
        mapped, total, mapping_details, unmapped_details = map_variable_units_to_opb(model, baseline_units, opb_map)
        print(f"  Variables mapped: {mapped}/{total}")
        
        stats.append({
            "file": cellml_path,
            "variables_total": total,
            "variables_mapped": mapped,
            "mapping_details": mapping_details,
            "unmapped_details": unmapped_details
        })
    
    # Save statistics
    with open("pmr_opb_mapping_stats_ce.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    
    print("\nMapping statistics saved to pmr_opb_mapping_stats_ce.json")
    
    return stats

def generate_comprehensive_statistics(stats_json="pmr_opb_mapping_stats_ce.json"):
    # Unit categories
    thermodynamic = {"K", "J", "mW", "S", "S_per_s"}
    quantities = {"um", "m2", "m3", "rad", "kg", "fmol", "kg_per_m2", "kg_per_m3", "mM", "mol_per_m2", "C_per_m2", "C_per_m3"}
    flow_rates = {"m_per_s", "m2_per_s", "m3_per_s", "rad_per_s", "kg_per_s", "fmol_per_s", "fA"}
    efforts = {"N", "J_per_m2", "Pa", "J_per_mol", "mV", "mM_per_s", "mol_per_m2_s", "C_per_m2_s", "C_per_m3_s"} 
    
    with open(stats_json, "r", encoding="utf-8") as f:
        stats = json.load(f)
    
    total_files = len(stats)
    total_vars = 0
    mapped_vars = 0
    unmapped_vars = 0
    
    mapped_units = []
    unmapped_units = []
    opb_codes = []
    
    category_counts = {"Quantities": 0, "Flow rates": 0, "Efforts": 0, "Thermodynamics": 0}
    
    for file_stat in stats:
        total_vars += file_stat.get("variables_total", 0)
        mapped_vars += file_stat.get("variables_mapped", 0)
        for detail in file_stat.get("mapping_details", []):
            unit = detail.get("mapped_to")
            opb_list = detail.get("opb_code")
            mapped_units.append(unit)
            # Handle OPB codes
            if isinstance(opb_list, list):
                if opb_list:
                    for opb in opb_list:
                        opb_codes.append(opb)
            elif opb_list:
                opb_codes.append(opb_list)
            # Categorize mapped units
            if opb_list:  # Only categorize if mapped to OPB
                if unit in thermodynamic:
                    category_counts["Thermodynamics"] += 1
                elif unit in quantities:
                    category_counts["Quantities"] += 1
                elif unit in flow_rates:
                    category_counts["Flow rates"] += 1
                elif unit in efforts:
                    category_counts["Efforts"] += 1
        # Add unmapped units
        if "unmapped_details" in file_stat:
            for detail in file_stat["unmapped_details"]:
                unmapped_units.append(detail.get("unit"))
        unmapped_vars += file_stat.get("variables_total", 0) - file_stat.get("variables_mapped", 0)
    
    # Top 10 mapped units
    from collections import Counter
    mapped_counter = Counter(mapped_units)
    unmapped_counter = Counter(unmapped_units)
    opb_counter = Counter(opb_codes)
    
    print("-----------")
    print("OVERVIEW")
    print("-----------")
    print(f"Total number of files processed: {total_files}")
    print(f"Total number of variables processed: {total_vars}")
    print(f"Number of variables successfully mapped: {mapped_vars}")
    print(f"Number of variables not mapped: {unmapped_vars}")
    
    print("\n--------------------------")
    print("CATEGORY BREAKDOWN")
    print("--------------------------")
    for cat, count in category_counts.items():
        percent = (count / mapped_vars * 100) if mapped_vars else 0
        print(f"{cat}: {count} ({percent:.1f}%)")
    
    print("\n------------------------")
    print("TOP 10 MAPPED UNITS")
    print("------------------------")
    for unit, count in mapped_counter.most_common(10):
        print(f"{unit}: {count}")
    
    print("\n---------------------------")
    print("TOP 10 UNMAPPED UNITS")
    print("---------------------------")
    for unit, count in unmapped_counter.most_common(10):
        print(f"{unit}: {count}")
    
    OPB_DESCRIPTIONS = {
        "OPB_01532": "Volumetric concentration of particles",
        "OPB_00340": "Concentration of chemical",
        "OPB_00378": "Chemical potential",
        "OPB_00509": "Fluid pressure",
        "OPB_01238": "Charge areal density",
        "OPB_01237": "Charge volumetric density",
        "OPB_00562": "Energy amount",
        "OPB_01053": "Mechanical stress",
        "OPB_00293": "Temperature",
        "OPB_00034": "Mechanical force",
        "OPB_00100": "Thermodynamic entropy amount",
        "OPB_00564": "Entropy flow rate",
        "OPB_00411": "Charge amount",
        "OPB_00592": "Chemical amount flow rate",
        "OPB_00544": "Particle flow rate",
        "OPB_01226": "Mass of solid entity",
        "OPB_01593": "Areal density of mass",
        "OPB_01619": "Volumnal density of matter",
        "OPB_01220": "Material flow rate",
        "OPB_00295": "Spatial area",
        "OPB_01643": "Tensile distortion velocity",
        "OPB_00523": "Spatial volume",
        "OPB_00299": "Fluid flow rate",
        "OPB_01058": "Membrane potential",
        "OPB_01169": "Electrodiffusional potential",
        "OPB_00563": "Energy flow rate",
        "OPB_00251": "Lineal translational velocity",
        "OPB_01529": "Areal concentration of chemical",
        "OPB_01530": "Areal concentration of particles",
        "OPB_01601": "Rotational displacement",
        "OPB_01064": "Spatial span",
        "OPB_01490": "Rotational solid velocity",
        "OPB_00402": "Temporal location",
        "OPB_00506": "Electrical potential",
        "OPB_00154": "Fluid volume",
        "OPB_01072": "Plane angle",
        "OPB_00318": "Charge flow rate",
        "OPB_00425": "Molar amount of chemical",
        "OPB_00593": "Density flow rate",
        "OPB_00269": "Translational displacement",
        "OPB_01376": "Tensile distortion",
    }
    
    print("\n-----------------------")
    print("TOP 10 OPB MAPPING")
    print("-----------------------")
    for opb, count in opb_counter.most_common(10):
        opb_clean = opb.strip(" ,;.")
        desc = OPB_DESCRIPTIONS.get(opb_clean, "")
        if desc:
            print(f"{opb}: {count} ({desc})")
        else:
            print(f"{opb}: {count}")

if __name__ == "__main__":
    stats = main()
    generate_comprehensive_statistics()

# # Latest version before considering composite units (10 Dec 2025)
# import os
# import libcellml
# import requests
# import json
# from rdflib import Graph

# PMR_WORKSPACE_DIR = os.path.expanduser("~/Downloads/modelCE")
# #BASELINE_UNITS_URL = "https://raw.githubusercontent.com/nickerso/cellml-to-fc/main/baseline_units.cellml"
# BASELINE_UNITS_URL = "baseline_units_new.cellml"
# RDF_OPB_URL = "https://raw.githubusercontent.com/nickerso/cellml-to-fc/main/rdf_unit_cellml.ttl"
# RDF_OPB_LOCAL = "rdf_unit_cellml.ttl"

# SI_BASE_UNITS_OPB = {
#     "ampere": "OPB_00318",    # Electric current
#     "kelvin": "OPB_00293",    # Temperature
#     "kilogram": "OPB_01226",  # Mass
#     "metre": "OPB_00269",     # Length (British spelling)
#     "mole": "OPB_00425",      # Amount of substance
#     "second": "OPB_00402",    # Time
# }

# def download_file(url, local_path):
#     if not os.path.exists(local_path):
#         r = requests.get(url)
#         r.raise_for_status()
#         with open(local_path, "w", encoding="utf-8") as f:
#             f.write(r.text)

# def find_cellml_files(root_dir):
#     cellml_files = []
#     for dirpath, dirs, files in os.walk(root_dir):
#         for file in files:
#             if file.endswith(".cellml"):
#                 cellml_files.append(os.path.join(dirpath, file))
#     return cellml_files

# def parse_baseline_units():
#     download_file(BASELINE_UNITS_URL, "baseline_units.cellml")
#     parser = libcellml.Parser()
#     parser.setStrict(False)
#     with open("baseline_units.cellml", "r", encoding="utf-8") as f:
#         baseline_content = f.read()
#     baseline_model = parser.parseModel(baseline_content)
#     baseline_units = {}
#     for i in range(baseline_model.unitsCount()):
#         units = baseline_model.units(i)
#         baseline_units[units.name()] = units
#     return baseline_units

# def load_opb_mappings(rdf_file_path=RDF_OPB_LOCAL):
#     download_file(RDF_OPB_URL, rdf_file_path)
#     opb_map = {}
#     with open(rdf_file_path, "r", encoding="utf-8") as f:
#         for line in f:
#             line = line.strip()
#             if not line or line.startswith("@prefix"):
#                 continue
#             if "is_unit_of:" in line and "opb:OPB_" in line:
#                 # ex:um is_unit_of: opb:OPB_00269, opb:OPB_01064 .
#                 parts = line.split()
#                 if parts[0].startswith("ex:"):
#                     unit_name = parts[0][3:]
#                     opb_codes = []
#                     # Find all opb:OPB_XXXX entries after 'is_unit_of:'
#                     opb_part = line.split("is_unit_of:")[1]
#                     for code in opb_part.split(","):
#                         code = code.strip().replace("opb:OPB_", "OPB_").replace(".", "").replace(";", "")
#                         if code.startswith("OPB_"):
#                             opb_codes.append(code)
#                     opb_map[unit_name] = opb_codes
#     return opb_map

# def resolve_imports(model, base_path):
#     importer = libcellml.Importer()
#     importer.resolveImports(model, base_path)
#     return importer

# def validate_model(model):
#     validator = libcellml.Validator()
#     validator.validateModel(model)
#     return validator.errorCount() == 0

# def get_unit_id(units):
#     if hasattr(units, 'id') and units.id():
#         return units.id()
#     elif hasattr(units, 'cmetaId') and units.cmetaId():
#         return units.cmetaId()
#     else:
#         return units.name()

# def map_variable_units_to_opb(model, baseline_units, opb_map):
#     mapped = 0
#     total = 0
#     mapping_details = []
#     unmapped_details = []
#     model_unit_names = [model.units(i).name() for i in range(model.unitsCount())]
#     print(f"    Components: {model.componentCount()}")
#     for i in range(model.componentCount()):
#         comp = model.component(i)
#         print(f"      Component '{comp.name()}': {comp.variableCount()} variables")
#         for j in range(comp.variableCount()):
#             var = comp.variable(j)
#             unit_obj = var.units()
#             if hasattr(unit_obj, "name"):
#                 unit_name = unit_obj.name()
#             else:
#                 unit_name = unit_obj
#             print(f"        Variable '{var.name()}' unit: '{unit_name}'")

#             # Check for SI base units first
#             if unit_name in SI_BASE_UNITS_OPB:
#                 opb_code = SI_BASE_UNITS_OPB[unit_name]
#                 mapping_details.append({
#                     "variable": var.name(),
#                     "unit": unit_name,
#                     "mapped_to": unit_name,
#                     "opb_code": [opb_code]
#                 })
#                 mapped += 1
#                 total += 1
#                 continue

#             # Find the units object from the model
#             units_obj = None
#             if unit_name in model_unit_names:
#                 units_obj = model.units(model_unit_names.index(unit_name))
#             elif unit_name in baseline_units:
#                 units_obj = baseline_units[unit_name]

#             if not units_obj:
#                 unmapped_details.append({
#                     "variable": var.name(),
#                     "unit": unit_name,
#                     "reason": "Unit not found in model, baseline, or SI base units"
#                 })
#                 continue

#             total += 1
#             mapped_this_unit = False
            
#             # FIX: Check compatibility with ALL baseline units, not just same-named ones
#             for base_name, base_units in baseline_units.items():
#                 if libcellml.Units.compatible(units_obj, base_units):
#                     opb_code = opb_map.get(base_name)
#                     mapping_details.append({
#                         "variable": var.name(),
#                         "unit": unit_name,
#                         "mapped_to": base_name,
#                         "opb_code": opb_code
#                     })
#                     mapped += 1
#                     mapped_this_unit = True
#                     print(f"          ✓ Mapped '{unit_name}' to baseline '{base_name}'")  # Debug
#                     break

#             if not mapped_this_unit:
#                 unmapped_details.append({
#                     "variable": var.name(),
#                     "unit": unit_name,
#                     "reason": "No compatible baseline unit found"
#                 })
#                 print(f"          ✗ No baseline unit compatible with '{unit_name}'")  # Debug

#     return mapped, total, mapping_details, unmapped_details

# def main():
#     print("Scanning for CellML files...")
#     cellml_files = find_cellml_files(PMR_WORKSPACE_DIR)
#     print(f"Found {len(cellml_files)} CellML files.")

#     print("Loading baseline units...")
#     baseline_units = parse_baseline_units()

#     print("Loading OPB mappings from RDF...")
#     opb_map = load_opb_mappings()

#     stats = []
#     for idx, cellml_path in enumerate(cellml_files, 1):
#         print(f"\n[{idx}/{len(cellml_files)}] Processing: {cellml_path}")
#         parser = libcellml.Parser()
#         parser.setStrict(False)
#         with open(cellml_path, "r", encoding="utf-8") as f:
#             content = f.read()
#         model = parser.parseModel(content)
#         if not model:
#             print("  Failed to parse model.")
#             continue

#         # Resolve imports
#         base_path = os.path.dirname(cellml_path)
#         resolve_imports(model, base_path)

#         # Validate model
#         valid = validate_model(model)
#         print(f"  Model valid: {valid}")

#         # Map variable units to OPB
#         mapped, total, mapping_details, unmapped_details = map_variable_units_to_opb(model, baseline_units, opb_map)
#         print(f"  Variables mapped: {mapped}/{total}")

#         stats.append({
#             "file": cellml_path,
#             "variables_total": total,
#             "variables_mapped": mapped,
#             "mapping_details": mapping_details,
#             "unmapped_details": unmapped_details
#         })

#     # Save statistics
#     with open("pmr_opb_mapping_stats_ce.json", "w", encoding="utf-8") as f:
#         json.dump(stats, f, indent=2, ensure_ascii=False)

#     print("\nMapping statistics saved to pmr_opb_mapping_stats_ce.json")

# def generate_comprehensive_statistics(stats_json="pmr_opb_mapping_stats_ce.json"):
#     # Unit categories
#     thermodynamic = {"K", "J", "mW", "S", "S_per_s"}
#     quantities = {"um", "m2", "m3", "rad", "kg", "fmol", "kg_per_m2", "kg_per_m3", "mM", "mol_per_m2", "C_per_m2", "C_per_m3"}
#     flow_rates = {"m_per_s", "m2_per_s", "m3_per_s", "rad_per_s", "kg_per_s", "fmol_per_s", "fA"}
#     efforts = {"N", "J_per_m2", "Pa", "J_per_mol", "mV", "mM_per_s", "mol_per_m2_s", "C_per_m2_s", "C_per_m3_s"} 

#     with open(stats_json, "r", encoding="utf-8") as f:
#         stats = json.load(f)

#     total_files = len(stats)
#     total_vars = 0
#     mapped_vars = 0
#     unmapped_vars = 0

#     mapped_units = []
#     unmapped_units = []
#     opb_codes = []

#     category_counts = {"Quantities": 0, "Flow rates": 0, "Efforts": 0, "Thermodynamics": 0}

#     for file_stat in stats:
#         total_vars += file_stat.get("variables_total", 0)
#         mapped_vars += file_stat.get("variables_mapped", 0)
#         for detail in file_stat.get("mapping_details", []):
#             unit = detail.get("mapped_to")
#             opb_list = detail.get("opb_code")
#             mapped_units.append(unit)
#             # Handle OPB codes (can be list or single value)
#             if isinstance(opb_list, list):
#                 if opb_list:
#                     for opb in opb_list:
#                         opb_codes.append(opb)
#                 else:
#                     unmapped_units.append(unit)
#             elif opb_list:
#                 opb_codes.append(opb_list)
#             else:
#                 unmapped_units.append(unit)
#             # Categorize mapped units
#             if opb_list:  # Only categorize if mapped to OPB
#                 if unit in thermodynamic:
#                     category_counts["Thermodynamics"] += 1
#                 elif unit in quantities:
#                     category_counts["Quantities"] += 1
#                 elif unit in flow_rates:
#                     category_counts["Flow rates"] += 1
#                 elif unit in efforts:
#                     category_counts["Efforts"] += 1
#         # Add unmapped units from unmapped_details if present
#         if "unmapped_details" in file_stat:
#             for detail in file_stat["unmapped_details"]:
#                 unmapped_units.append(detail.get("unit"))
#         unmapped_vars += file_stat.get("variables_total", 0) - file_stat.get("variables_mapped", 0)

#     # Top 10 mapped units
#     from collections import Counter
#     mapped_counter = Counter(mapped_units)
#     unmapped_counter = Counter(unmapped_units)
#     opb_counter = Counter(opb_codes)

#     print("-----------")
#     print("OVERVIEW")
#     print("-----------")
#     print(f"Total number of files processed: {total_files}")
#     print(f"Total number of variables processed: {total_vars}")
#     print(f"Number of variables successfully mapped: {mapped_vars}")
#     print(f"Number of variables not mapped: {unmapped_vars}")

#     print("\n--------------------------")
#     print("CATEGORY BREAKDOWN")
#     print("--------------------------")
#     for cat, count in category_counts.items():
#         percent = (count / mapped_vars * 100) if mapped_vars else 0
#         print(f"{cat}: {count} ({percent:.1f}%)")

#     print("\n------------------------")
#     print("TOP 10 MAPPED UNITS")
#     print("------------------------")
#     for unit, count in mapped_counter.most_common(10):
#         print(f"{unit}: {count}")

#     print("\n---------------------------")
#     print("TOP 10 UNMAPPED UNITS")
#     print("---------------------------")
#     for unit, count in unmapped_counter.most_common(10):
#         print(f"{unit}: {count}")

#     OPB_DESCRIPTIONS = {
#         "OPB_01532": "Volumetric concentration of particles",
#          "OPB_00340": "Concentration of chemical",
#          "OPB_00378": "Chemical potential",
#          "OPB_00509": "Fluid pressure",
#          "OPB_01238": "Charge areal density",
#          "OPB_01237": "Charge volumetric density",
#          "OPB_00562": "Energy amount",
#          "OPB_01053": "Mechanical stress",
#          "OPB_00293": "Temperature",
#          "OPB_00034": "Mechanical force",
#          "OPB_00100": "Thermodynamic entropy amount",
#          "OPB_00564": "Entropy flow rate",
#          "OPB_00411": "Charge amount",
#          "OPB_00592": "Chemical amount flow rate",
#          "OPB_00544": "Particle flow rate",
#          "OPB_01226": "Mass of solid entity",
#          "OPB_01593": "Areal density of mass",
#          "OPB_01619": "Volumnal density of matter",
#          "OPB_01220": "Material flow rate",
#          "OPB_00295": "Spatial area",
#          "OPB_01643": "Tensile distortion velocity",
#          "OPB_00523": "Spatial volume",
#          "OPB_00299": "Fluid flow rate",
#          "OPB_01058": "Membrane potential",
#          "OPB_01169": "Electrodiffusional potential",
#          "OPB_00563": "Energy flow rate",
#          "OPB_00251": "Lineal translational velocity",
#          "OPB_01529": "Areal concentration of chemical",
#          "OPB_01530": "Areal concentration of particles",
#          "OPB_01601": "Rotational displacement",
#          "OPB_01064": "Spatial span",
#          "OPB_01490": "Rotational solid velocity",
#          "OPB_00402": "Temporal location",
#          "OPB_00506": "Electrical potential",
#          "OPB_00154": "Fluid volume",
#          "OPB_01072": "Plane angle",
#          "OPB_00318": "Charge flow rate",
#          "OPB_00425": "Molar amount of chemical",
#          "OPB_00593": "Density flow rate",
#          "OPB_00269": "Translational displacement",
#          "OPB_01376": "Tensile distortion",

#     }

#     print("\n-----------------------")
#     print("TOP 10 OPB MAPPING")
#     print("-----------------------")
#     for opb, count in opb_counter.most_common(10):
#         opb_clean = opb.strip(" ,;.")
#         desc = OPB_DESCRIPTIONS.get(opb_clean, "")
#         if desc:
#             print(f"{opb}: {count} ({desc})")
#         else:
#             print(f"{opb}: {count}")

# if __name__ == "__main__":
#     main()
#     generate_comprehensive_statistics()


