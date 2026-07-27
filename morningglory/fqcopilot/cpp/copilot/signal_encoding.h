#pragma once

namespace ClxSignalEncoding
{
    constexpr int MIN_OCCURRENCE = 1;
    constexpr int MAX_OCCURRENCE = 99;

    // occurrence <= 0 is invalid and produces no signal. Values above the
    // two-digit wire limit saturate at 99; 99 therefore means "99 or more".
    constexpr int encode(int model_id, int occurrence, int signed_entrypoint)
    {
        if (model_id < 0 || occurrence < MIN_OCCURRENCE ||
            signed_entrypoint == 0 || signed_entrypoint < -7 ||
            signed_entrypoint > 7)
        {
            return 0;
        }
        const int bounded_occurrence =
            occurrence > MAX_OCCURRENCE ? MAX_OCCURRENCE : occurrence;
        const int abs_entrypoint =
            signed_entrypoint >= 0 ? signed_entrypoint : -signed_entrypoint;
        const int value =
            model_id * 1000 + bounded_occurrence * 100 + abs_entrypoint;
        return signed_entrypoint > 0 ? value : -value;
    }

    constexpr int magnitude(int signal)
    {
        return signal >= 0 ? signal : -signal;
    }

    // The integer is not self-describing once occurrence reaches 10. The
    // trusted matrix row supplies source_model_id and makes decoding exact.
    constexpr int occurrence_for_model(int signal, int source_model_id)
    {
        return (magnitude(signal) - source_model_id * 1000) / 100;
    }

    constexpr int reencode_for_model(
        int signal, int source_model_id, int target_model_id)
    {
        if (signal == 0)
        {
            return 0;
        }
        const int abs_entrypoint = magnitude(signal) % 100;
        const int signed_entrypoint = signal > 0 ? abs_entrypoint : -abs_entrypoint;
        return encode(
            target_model_id,
            occurrence_for_model(signal, source_model_id),
            signed_entrypoint);
    }
}
