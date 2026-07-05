from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files('tensorflow')
binaries = collect_dynamic_libs('tensorflow')
hiddenimports = [
    'tensorflow.python', 
    'tensorflow.python.platform', 
    'tensorflow.python.framework', 
    'tensorflow.core', 
    'tensorflow.core.framework',
    'tensorflow.python.keras',
    'tensorflow.python.ops',
    'tensorflow.python.saved_model'
]
