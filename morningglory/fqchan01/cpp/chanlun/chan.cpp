#include "chan.h"

void Chan::set_bi_mode(int bi_mode)
{
    if (bi_mode < 4)
    {
        bi_mode = 4;
    }
    this->options->bi_mode = bi_mode;
}

int Chan::get_bi_mode()
{
    return this->options->bi_mode;
}

void Chan::set_force_wave_stick_count(int force_wave_stick_count)
{
    this->options->force_wave_stick_count = force_wave_stick_count;
}

int Chan::get_force_wave_stick_count()
{
    return this->options->force_wave_stick_count;
}

void Chan::set_allow_pivot_across(int allow_pivot_across)
{
    this->options->allow_pivot_across = allow_pivot_across;
}

int Chan::get_allow_pivot_across()
{
    return this->options->allow_pivot_across;
}

void Chan::set_merge_non_complehensive_wave(int merge_non_complehensive_wave)
{
    this->options->merge_non_complehensive_wave = merge_non_complehensive_wave;
}

int Chan::get_merge_non_complehensive_wave()
{
    return this->options->merge_non_complehensive_wave;
}

void Chan::set_inclusion_mode(int inclusion_mode)
{
    this->options->inclusion_mode = inclusion_mode;
}

int Chan::get_inclusion_mode()
{
    return this->options->inclusion_mode;
}

ChanOptions &Chan::get_options()
{
    return *options;
}

thread_local ChanProxy *ChanProxy::instance = nullptr;
thread_local std::mutex ChanProxy::mutex;

ChanProxy::ChanProxy() : chan(std::make_unique<Chan>()) {}

ChanProxy::~ChanProxy()
{
    if (this->instance)
    {
        delete instance;
        instance = nullptr;
    } 
}

void ChanProxy::reset()
{
    std::lock_guard<std::mutex> lock(mutex);
    this->chan->reset();
}
ChanProxy &ChanProxy::get_instance()
{
    if (!instance)
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (!instance)
        {
            instance = new ChanProxy();
        }
    }
    return *instance;
}

void ChanProxy::set_bi_mode(int bi_mode)
{
    this->chan->set_bi_mode(bi_mode);
}

int ChanProxy::get_bi_mode()
{
    return this->chan->get_bi_mode();
}

void ChanProxy::set_force_wave_stick_count(int force_wave_stick_count)
{
    this->chan->set_force_wave_stick_count(force_wave_stick_count);
}

int ChanProxy::get_force_wave_stick_count()
{
    return this->chan->get_force_wave_stick_count();
}

void ChanProxy::set_allow_pivot_across(int allow_pivot_across)
{
    this->chan->set_allow_pivot_across(allow_pivot_across);
}

int ChanProxy::get_allow_pivot_across()
{
    return this->chan->get_allow_pivot_across();
}

void ChanProxy::set_merge_non_complehensive_wave(int merge_non_complehensive_wave)
{
    this->chan->set_merge_non_complehensive_wave(merge_non_complehensive_wave);
}

int ChanProxy::get_merge_non_complehensive_wave()
{
    return this->chan->get_merge_non_complehensive_wave();
}

void ChanProxy::set_inclusion_mode(int inclusion_mode)
{
    this->chan->set_inclusion_mode(inclusion_mode);
}

int ChanProxy::get_inclusion_mode()
{
    return this->chan->get_inclusion_mode();
}

ChanOptions &ChanProxy::get_options()
{
    return this->chan->get_options();
}
