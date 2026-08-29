on run argv
    if (count of argv) < 2 then return
    display notification (item 2 of argv) with title (item 1 of argv)
end run
