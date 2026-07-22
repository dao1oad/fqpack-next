#include "signal_encoding.h"

#include <cassert>

using ClxSignalEncoding::encode;
using ClxSignalEncoding::occurrence_for_model;
using ClxSignalEncoding::reencode_for_model;

static_assert(encode(8, 0, 7) == 0, "zero occurrence must fail closed");
static_assert(encode(8, -1, -7) == 0, "negative occurrence must fail closed");
static_assert(encode(-1, 1, 7) == 0, "negative model id must fail closed");
static_assert(encode(8, 1, 0) == 0, "zero entrypoint must fail closed");
static_assert(encode(8, 1, 8) == 0, "entrypoint above seven must fail closed");
static_assert(encode(8, 1, -8) == 0, "entrypoint below minus seven must fail closed");
static_assert(encode(101, 1, 7) == 101107, "positive model ids remain extensible");
static_assert(encode(8, 9, 7) == 8907, "single-digit occurrence changed");
static_assert(encode(8, 10, 7) == 9007, "two-digit occurrence changed");
static_assert(encode(8, 99, 7) == 17907, "occurrence 99 changed");
static_assert(encode(8, 100, 7) == 17907, "occurrence must saturate at 99");
static_assert(encode(8, 100, -7) == -17907, "negative signal must retain direction");

static_assert(occurrence_for_model(8907, 8) == 9, "decode occurrence 9");
static_assert(occurrence_for_model(9007, 8) == 10, "decode occurrence 10");
static_assert(occurrence_for_model(17907, 8) == 99, "decode occurrence 99");

static_assert(reencode_for_model(8907, 8, 13) == 13907, "S0013 occurrence 9");
static_assert(reencode_for_model(9007, 8, 13) == 14007, "S0013 occurrence 10");
static_assert(reencode_for_model(17907, 8, 13) == 22907, "S0013 occurrence 99");
static_assert(reencode_for_model(18007, 8, 13) == 22907, "S0013 occurrence 100");
static_assert(reencode_for_model(-8907, 8, 13) == -13907, "negative S0013 occurrence 9");
static_assert(reencode_for_model(-9007, 8, 13) == -14007, "negative S0013 occurrence 10");
static_assert(reencode_for_model(-17907, 8, 13) == -22907, "negative S0013 occurrence 99");
static_assert(reencode_for_model(-18007, 8, 13) == -22907, "negative S0013 occurrence 100");

static_assert(reencode_for_model(8907, 8, 14) == 14907, "S0014 occurrence 9");
static_assert(reencode_for_model(9007, 8, 14) == 15007, "S0014 occurrence 10");
static_assert(reencode_for_model(17907, 8, 14) == 23907, "S0014 occurrence 99");
static_assert(reencode_for_model(18007, 8, 14) == 23907, "S0014 occurrence 100");
static_assert(reencode_for_model(-8907, 8, 14) == -14907, "negative S0014 occurrence 9");
static_assert(reencode_for_model(-9007, 8, 14) == -15007, "negative S0014 occurrence 10");
static_assert(reencode_for_model(-17907, 8, 14) == -23907, "negative S0014 occurrence 99");
static_assert(reencode_for_model(-18007, 8, 14) == -23907, "negative S0014 occurrence 100");

static_assert(reencode_for_model(8007, 8, 13) == 0, "invalid source occurrence");
static_assert(reencode_for_model(-8007, 8, 14) == 0, "invalid negative source occurrence");
static_assert(reencode_for_model(8100, 8, 13) == 0, "invalid source entrypoint zero");
static_assert(reencode_for_model(-8108, 8, 14) == 0, "invalid source entrypoint eight");

int main()
{
    assert(reencode_for_model(9007, 8, 13) == 14007);
    assert(reencode_for_model(-9007, 8, 14) == -15007);
    return 0;
}
