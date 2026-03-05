add_rules("mode.release", "mode.debug")

-- 全局设置 UTF-8 编码
if is_plat("windows") then
    add_cxxflags("/utf-8")
    add_cflags("/utf-8")
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

-- 编译通达信
target("tdx")
    add_global_defines()
    set_kind("shared")
    set_arch("x86")
    set_targetdir("tdx")
    set_basename("fqchan01")
    add_files_recursive("cpp")
    add_cxflags("/EHsc")
    
-- 编译KT交易师
target("kt")
    add_global_defines()
    set_kind("shared")
    set_arch("x86")
    set_targetdir("kt")
    set_basename("fqchan01")
    add_files_recursive("cpp")
    add_cxflags("/EHsc")

-- 编译金字塔64位
target("jzt")
    add_global_defines()
    set_kind("shared")
    set_arch("x64")
    set_targetdir("jzt")
    set_basename("fqchan01")
    add_files_recursive("cpp")
    add_defines("_X64")
    add_cxflags("/EHsc")


-- 编译金字塔32位
target("jzt32")
    add_global_defines()
    set_kind("shared")
    set_arch("x86")
    set_targetdir("jzt32")
    set_basename("fqchan01")
    add_files_recursive("cpp")
    add_cxflags("/EHsc")

-- 编译大智慧
target("dzh")
    add_global_defines()
    set_kind("shared")
    set_arch("x64")
    set_targetdir("dzh")
    set_basename("fqchan01")
    add_files_recursive("cpp")
    add_defines("_X64", "_DZH")
    add_cxflags("/EHsc")
