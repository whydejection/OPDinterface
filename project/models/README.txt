В этом архиве лежат два файла:
- swin_transformer.onnx
- swin_transformer.onnx.data

Для корректного использования файлов они должны лежать в одной папке.

Входные данные:
- формат .npy float32
- размерность (1, 128, 128) или (128, 128), первая ось - это канал. 
- содержимое - прореженные данные

Выходные данные:
- формат .npy float32
- размерность (1, 128, 128) или (128, 128)
- содержимое - восставновленная сейсмограмма

Пример входных данных:
Сейсмограмма, порезанная на патчи, например thinned_chunk_0.npy

Пример выходных данных:
Восстановленная сейсмограмма, например denoised.npy

Пример использования на python:
import numpy as np
import onnxruntime as ort

# Загрузка модели
sess = ort.InferenceSession("swin_transformer.onnx")

# Загрузка входного патча (например, thinned_patch.npy)
input_patch = np.load("thinned_patch.npy").astype(np.float32)  # форма (128, 128)

# Добавление осей batch и channel: (1, 1, 128, 128)
input_tensor = input_patch[np.newaxis, np.newaxis, ...]

# Инференс
outputs = sess.run(['output'], {'input': input_tensor})
result = outputs[0]          # (1, 1, 128, 128)
result_patch = result[0, 0]  # (128, 128)

# Сохранение
np.save("interpolated_patch.npy", result_patch)