#include "../cpp/copilot/signal_encoding.h"

int main()
{
    using namespace ClxSignalEncoding;

    const int buy = pack_tdx_signal_and_base_mask(104, 4);
    if (unpack_tdx_signal(buy) != 104 ||
        unpack_tdx_trigger_mask(buy) != 12)
    {
        return 1;
    }

    const int sell = pack_tdx_signal_and_base_mask(-17007, 2);
    if (unpack_tdx_signal(sell) != -17007 ||
        unpack_tdx_trigger_mask(sell) != 66)
    {
        return 2;
    }

    const int maximum = pack_tdx_signal_and_base_mask(26907, 127);
    if (maximum >= (1 << 24) ||
        static_cast<int>(static_cast<float>(maximum)) != maximum)
    {
        return 3;
    }
    return 0;
}
