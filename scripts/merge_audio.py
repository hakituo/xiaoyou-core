import os
import soundfile as sf
import numpy as np
from typing import List


def merge_wav_files(input_files: List[str], output_file: str):
    """
    拼接多个 WAV 文件为一个。

    :param input_files: 输入文件路径列表
    :param output_file: 输出文件路径
    """
    if not input_files:
        print("错误: 没有输入文件。")
        return

    data_list = []
    samplerate = None
    channels = None

    print(f"开始拼接 {len(input_files)} 个音频文件...")

    for file_path in input_files:
        if not os.path.exists(file_path):
            print(f"警告: 文件不存在，已跳过: {file_path}")
            continue

        try:
            data, sr = sf.read(file_path)

            # 检查采样率是否一致
            if samplerate is None:
                samplerate = sr
            elif samplerate != sr:
                print(f"警告: 采样率不匹配 ({sr} != {samplerate})，文件: {file_path}")
                # 这里简单处理，实际可能需要重采样
                continue

            # 检查通道数是否一致
            curr_channels = data.shape[1] if len(data.shape) > 1 else 1
            if channels is None:
                channels = curr_channels
            elif channels != curr_channels:
                print(
                    f"警告: 通道数不匹配 ({curr_channels} != {channels})，文件: {file_path}"
                )
                continue

            data_list.append(data)
            print(f"已加载: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"错误: 无法读取文件 {file_path}: {e}")

    if not data_list:
        print("错误: 没有可拼接的有效音频数据。")
        return

    # 拼接数据
    merged_data = np.concatenate(data_list, axis=0)

    # 写入输出文件
    try:
        sf.write(output_file, merged_data, samplerate)
        print(f"\n拼接成功！输出文件: {output_file}")
        print(f"总时长预计: {len(merged_data) / samplerate:.2f} 秒")
    except Exception as e:
        print(f"错误: 写入输出文件失败: {e}")


if __name__ == "__main__":
    # 用户提供的文件列表
    files_to_merge = [
        r"D:\AI\xiaoyou-core\output\voice\tts_qwen3_20260209_000052.wav",
        r"D:\AI\xiaoyou-core\output\voice\tts_qwen3_20260209_000117.wav",
        r"D:\AI\xiaoyou-core\output\voice\tts_qwen3_20260209_000129.wav",
        r"D:\AI\xiaoyou-core\output\voice\tts_qwen3_20260209_000139.wav",
    ]

    output_path = r"d:\AI\xiaoyou-core\output\voice\merged_qwen3_20260209.wav"

    merge_wav_files(files_to_merge, output_path)
