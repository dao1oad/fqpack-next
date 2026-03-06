add_rules("mode.release", "mode.debug")

-- 全局设置 UTF-8 编码
if is_plat("windows") then
    add_cxxflags("/utf-8")
    add_cflags("/utf-8")
end

function _trim(s)
    return (s or ""):gsub("^%s+", ""):gsub("%s+$", "")
end

function _detect_python()
    local py_inc = _trim(os.getenv("FQ_PY_INC") or "")
    local py_libdir = _trim(os.getenv("FQ_PY_LIBDIR") or "")
    local py_lib = _trim(os.getenv("FQ_PY_LIB") or "")
    local py_base = _trim(os.getenv("FQ_PY_BASE") or "")

    if py_base ~= "" then
        if py_inc == "" then
            py_inc = path.join(py_base, "Include")
        end
        if py_libdir == "" then
            py_libdir = path.join(py_base, "libs")
        end
    end

    if py_lib == "" and py_libdir ~= "" then
        local candidates = os.files(path.join(py_libdir, "python*.lib"))
        for _, f in ipairs(candidates) do
            local base = path.basename(f)
            if base ~= "python3" then
                py_lib = base
                break
            end
        end
        if py_lib == "" then
            for _, f in ipairs(candidates) do
                local base = path.basename(f)
                if base == "python3" then
                    py_lib = base
                    break
                end
            end
        end
    end

    local pybind_inc = _trim(os.getenv("FQ_PYBIND_INC") or "")
    if pybind_inc == "" and py_base ~= "" then
        pybind_inc = path.join(py_base, "Lib", "site-packages", "pybind11", "include")
    end

    return py_inc, py_libdir, py_lib, pybind_inc
end

function add_files_recursive(dir)
    for _, file in ipairs(os.files(path.join(dir, "*.cpp"))) do
        add_files(file)
    end
    for _, sub_dir in ipairs(os.dirs(path.join(dir, "*"))) do
        add_files_recursive(sub_dir)
    end
end

function add_global_defines()
    -- 只要注释掉相应的配置行，就是去掉该特性。
    add_defines(
        "_FORCE_SWELL_WHEN_9WAVE"       -- 9笔强制成段
        ,"_GAP_COUNT_AS_ONE_BAR"         -- 跳空缺口计数1根K线
        ,"_RIPPLE_REVERSE_WAVE_NO_MERGE" -- 小转大笔不合并
        -- ,"_ALLOW_SECOND_HIGH_LOW_SWELL" -- 允许次高次低成段
    )
end

-- 编译通达信版本
target("tdx")
    add_global_defines()
    set_kind("shared")
    set_arch("x86")
    set_targetdir("tdx/dlls")
    set_basename("fqcopilot")
    add_files_recursive("cpp")
    add_cxflags("/EHsc")

-- 编译通达信64位版本
target("tdx64")
    add_global_defines()
    set_kind("shared")
    set_arch("x64")
    set_targetdir("tdx64/dlls")
    set_basename("fqcopilot")
    add_files_recursive("cpp")
    add_defines("MAKE_X64")
    add_cxflags("/EHsc")

-- 编译KT交易师版本
target("kt")
    add_global_defines()
    set_kind("shared")
    set_arch("x86")
    set_targetdir("kt/dlls")
    set_basename("fqcopilot")
    add_files_recursive("cpp")
    add_cxflags("/EHsc")

-- 编译金字塔版本
target("jzt")
    add_global_defines()
    set_kind("shared")
    set_arch("x64")
    set_targetdir("jzt/dlls")
    set_basename("fqcopilot")
    add_files_recursive("cpp")
    add_defines("MAKE_X64")
    add_cxflags("/EHsc")

-- 编译金字塔32位版本
target("jzt32")
    add_global_defines()
    set_kind("shared")
    set_arch("x86")
    set_targetdir("jzt32/dlls")
    set_basename("fqcopilot")
    add_files_recursive("cpp")
    add_cxflags("/EHsc")

-- 编译大智慧版本
target("dzh")
    add_global_defines()
    set_kind("shared")
    set_arch("x64")
    set_targetdir("dzh/dlls")
    set_basename("fqcopilot")
    add_files_recursive("cpp")
    add_defines("MAKE_X64", "MAKE_DZH")
    add_cxflags("/EHsc")

-- 编译MT5版本
target("mt5")
    add_global_defines()
    set_kind("shared")
    set_arch("x64")
    set_targetdir("mt5/dlls")
    set_basename("fqcopilot")
    add_files_recursive("cpp")
    add_defines("MAKE_X64")
    add_cxflags("/EHsc")

-- fullcalc Python 扩展 (chanlun + CLX + stop-loss)
target("fullcalc_py")
    add_global_defines()
    set_kind("shared")
    set_basename("fullcalc")
    set_filename("fullcalc.pyd")
    set_arch("x64")
    set_targetdir("python")
    set_languages("cxx17")
    set_optimize("none")

    local py_inc, py_libdir, py_lib, pybind_inc = _detect_python()
    if py_inc ~= "" then
        add_includedirs(py_inc)
    end
    if pybind_inc ~= "" and os.isdir(pybind_inc) then
        add_includedirs(pybind_inc)
    end
    add_includedirs("fullcalc", "cpp", {public = true})
    if py_libdir ~= "" then
        add_linkdirs(py_libdir)
    end
    if py_lib ~= "" then
        add_links(py_lib)
    end

    add_files("fullcalc/*.cpp")
    add_files_recursive("cpp")

    -- Use fqchan04 chanlun sources (keep algorithm consistent with project)
    remove_files("cpp/chanlun/*.cpp")
    add_files("../fqchan04/cpp/chanlun/*.cpp")
    add_includedirs("../fqchan04/cpp", {public = true})

    add_defines("MAKE_X64")
    add_cxflags("/EHsc", "/d2SSAOptimizer-", "/Od")
