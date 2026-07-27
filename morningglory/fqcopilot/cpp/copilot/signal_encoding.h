#pragma once

namespace ClxSignalEncoding
{
    constexpr int MIN_OCCURRENCE = 1;
    constexpr int MAX_OCCURRENCE = 99;
    constexpr int TDX_TRIGGER_MASK_BASE = 1 << 7;
    constexpr int TDX_TRIGGER_MASK_LIMIT = TDX_TRIGGER_MASK_BASE - 1;

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

    // Float32 exactly represents every packed CLX value:
    // max abs(signal)=26907, so max packed value is 3,444,223 (<2^24).
    constexpr int pack_tdx_signal_and_base_mask(int signal, int base_mask)
    {
        if (signal == 0)
        {
            return 0;
        }
        const int primary_entrypoint = magnitude(signal) % 100;
        const int primary_bit =
            primary_entrypoint >= 1 && primary_entrypoint <= 7
                ? 1 << (primary_entrypoint - 1)
                : 0;
        const int completed_mask =
            (base_mask | primary_bit) & TDX_TRIGGER_MASK_LIMIT;
        const int packed_magnitude =
            magnitude(signal) * TDX_TRIGGER_MASK_BASE + completed_mask;
        return signal > 0 ? packed_magnitude : -packed_magnitude;
    }

    constexpr int unpack_tdx_signal(int packed)
    {
        const int unpacked =
            magnitude(packed) / TDX_TRIGGER_MASK_BASE;
        return packed >= 0 ? unpacked : -unpacked;
    }

    constexpr int unpack_tdx_trigger_mask(int packed)
    {
        return magnitude(packed) % TDX_TRIGGER_MASK_BASE;
    }

    static_assert(
        unpack_tdx_signal(pack_tdx_signal_and_base_mask(104, 4)) == 104,
        "TDX packed signal must round-trip");
    static_assert(
        unpack_tdx_trigger_mask(pack_tdx_signal_and_base_mask(104, 4)) == 12,
        "TDX packed mask must include the primary trigger bit");
}
