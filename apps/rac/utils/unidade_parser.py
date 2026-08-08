#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse medication dosage forms and map to standard units
"""

def parse_unidade_from_name(name: str) -> str:
    """Parse medication name and determine standard unit based on dosage form.
    
    Priority order:
    1. Injections → "un" (highest priority)
    2. Topical → "un"
    3. Liquids/solutions → "frs" 
    4. Solid forms → "comp"
    
    Returns:
        'un' - for injections, topical products
        'comp' - for tablets, capsules, solid oral forms  
        'frs' - for liquids, solutions, inhalations
    """
    name_lower = name.lower()
    
    # Injections - highest priority, individual units
    if 'inj.' in name_lower:
        return 'un'
    
    # Topical products - individual units (second priority)
    topical_patterns = [
        'pomada',        # ointment
        'creme',         # cream
        'gel',           # gel
    ]
    
    for pattern in topical_patterns:
        if pattern in name_lower:
            return 'un'
    
    # Liquids and solutions - frascas (third priority)
    liquid_patterns = [
        'mg/ml',         # milligrams per milliliter
        'mcg/ml',        # micrograms per milliliter
        'ui/ml',         # units per milliliter
        'sol. oral',     # oral solution
        'xarope',        # syrup
        'suspensao',     # suspension
        'sol. para',     # solution for (anything)
        'nebulizacao',   # nebulization
        'aerossol',      # aerosol/inhalation
        'spray',         # spray
        'oftalmica',     # eye drops
        'capilar',       # scalp solution
        'nasal',         # nasal spray
    ]
    
    for pattern in liquid_patterns:
        if pattern in name_lower:
            return 'frs'
    
    # Solid oral forms (tablets/capsules) - component (lowest priority)
    if 'capsula' in name_lower or 'comprimido' in name_lower:
        return 'comp'
    
    # Check for mg/mcg/ui patterns that are NOT part of liquid forms
    if (' mg ' in name_lower or name_lower.endswith(' mg')):
        if 'mg/ml' not in name_lower:
            return 'comp'
    if (' mcg ' in name_lower or name_lower.endswith(' mcg')):
        if 'mcg/ml' not in name_lower:
            return 'comp'
    if (' ui ' in name_lower or name_lower.endswith(' ui')):
        if 'ui/ml' not in name_lower:
            return 'comp'
    
    # Default to 'un' if no pattern matches
    return 'un'


# Test function
if __name__ == "__main__":
    test_cases = [
        ("abatacepte 125 mg inj.", "un"),
        ("atorvastatina 20 mg", "comp"),
        ("atorvastatina 20 mg/ml", "frs"),
        ("dapagliflozina 10 mg", "comp"),
        ("codeina 3 mg/ml sol. oral", "frs"),
        ("codeina 30 mg", "comp"),
        ("etossuximida 50 mg/ml xarope", "frs"),
        ("calcipotriol 50 mcg pomada", "un"),
        ("calcitriol 0,25 mcg capsula", "comp"),
        ("lanreotida 120 mg inj.", "un"),
        ("pentoxifilina 400 mg/ml inj.", "un"),
        ("codeina 30 mg/ml inj.", "un"),
        ("formoterol 12 mcg aerossol", "frs"),
        ("pilocarpina 20 mg/ml sol. oftalmica", "frs"),
        ("clobetasol 0,5 mg/g creme", "un"),
        ("mesalazina 400 mg", "comp"),
        ("calcitonina 200 ui spray nasal", "frs"),
        ("ibuprofeno 600 mg", "comp"),
        ("dipropionato de beclometasona 100 mcg", "comp"),
    ]
    
    print("Testing parse_unidade_from_name:")
    print("-" * 50)
    for name, expected in test_cases:
        result = parse_unidade_from_name(name)
        status = "✓" if result == expected else "✗"
        print(f"{status} {name:<50} → {result} (expected: {expected})")