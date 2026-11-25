-- Kéo thả thư mục/video lên icon app -> mở giao diện Cắt Tutorial trong trình duyệt.
-- Mở app trực tiếp (không kéo gì) -> mở giao diện trống để chọn thư mục.
on launchUI(argText)
	set appPath to POSIX path of (path to me)
	set toolDir to do shell script "dirname " & quoted form of appPath
	do shell script "nohup " & quoted form of (toolDir & "/ui.sh") & argText & " >/dev/null 2>&1 &"
end launchUI

on open theItems
	-- thả một hay nhiều thư mục (hoặc thư mục cha chứa các thư mục con) -> thêm hết vào giao diện
	set args to ""
	repeat with f in theItems
		set args to args & " " & quoted form of (POSIX path of f)
	end repeat
	launchUI(args)
end open

on run
	launchUI("")
end run
