"""A minimal in-memory tkinter stand-in so the desktop UI can be driven
headlessly (CI boxes and containers rarely have a display or Tk built).

Only the surface the game actually uses is implemented. Widgets record
their configuration; Canvas records draw calls; PhotoImage stores real
pixels (so sprite-building bugs still crash); `after` callbacks queue up
in AFTER_QUEUE for the test to pump manually via pump_after().
"""

END = "end"

AFTER_QUEUE = []   # (callback) in scheduling order; delays are ignored
_FOCUSED = [None]  # widget passed to focus_set() most recently
CLIPBOARD = [""]


class TclError(Exception):
    pass


def pump_after(rounds=1):
    """Run every queued after() callback; repeat for chained callbacks."""
    for _ in range(rounds):
        pending, AFTER_QUEUE[:] = AFTER_QUEUE[:], []
        for fn in pending:
            fn()


class PhotoImage:
    def __init__(self, width=16, height=16):
        self.width_px = width
        self.height_px = height
        self.pixels = {}

    def put(self, colors, to=(0, 0)):
        # colors is "{#rrggbb #rrggbb ...}" - one horizontal run.
        x0, y = to
        run = colors.strip("{}").split()
        for i, color in enumerate(run):
            if not (color.startswith("#") and len(color) == 7):
                raise TclError(f"bad color {color!r}")
            self.pixels[(x0 + i, y)] = color

    def zoom(self, zx, zy=None):
        zy = zx if zy is None else zy
        out = PhotoImage(self.width_px * zx, self.height_px * zy)
        for (x, y), color in self.pixels.items():
            for dy in range(zy):
                for dx in range(zx):
                    out.pixels[(x * zx + dx, y * zy + dy)] = color
        return out


class Widget:
    def __init__(self, master=None, **kw):
        self.master = master
        self.kw = dict(kw)
        self.destroyed = False
        self.packed = False

    # -- config ---------------------------------------------------------
    def configure(self, **kw):
        self.kw.update(kw)

    config = configure

    def cget(self, key):
        return self.kw.get(key, "")

    def __getitem__(self, key):
        return self.kw.get(key, "")

    def __setitem__(self, key, value):
        self.kw[key] = value

    # -- geometry (recorded, never laid out) ------------------------------
    def pack(self, **kw):
        self.packed = True

    def place(self, **kw):
        self.packed = True

    def grid(self, **kw):
        self.packed = True

    def pack_forget(self):
        self.packed = False

    place_forget = grid_forget = pack_forget

    def pack_propagate(self, flag=None):
        pass

    grid_propagate = pack_propagate

    # -- misc -------------------------------------------------------------
    def bind(self, *a, **kw):
        pass

    def focus_set(self):
        _FOCUSED[0] = self

    def destroy(self):
        self.destroyed = True
        self.packed = False

    def winfo_children(self):
        return []

    def update_idletasks(self):
        pass


class Frame(Widget):
    pass


class Label(Widget):
    pass


class Button(Widget):
    def invoke(self):
        if self.kw.get("state") == "disabled" or self.destroyed:
            return
        command = self.kw.get("command")
        if command:
            command()


class Entry(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.content = ""

    def get(self):
        return self.content

    def insert(self, index, text):
        self.content += text

    def delete(self, first, last=None):
        self.content = ""


class Text(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.content = ""

    def insert(self, index, text):
        self.content += text

    def delete(self, first, last=None):
        self.content = ""

    def get(self, first, last=None):
        return self.content

    def see(self, index):
        pass


class Listbox(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.items = []
        self.item_kw = {}
        self.selection = ()

    def insert(self, index, item):
        self.items.append(item)

    def delete(self, first, last=None):
        self.items = []
        self.item_kw = {}
        self.selection = ()

    def size(self):
        return len(self.items)

    def itemconfig(self, index, **kw):
        if not 0 <= index < len(self.items):
            raise TclError("bad index")
        self.item_kw.setdefault(index, {}).update(kw)

    def curselection(self):
        return self.selection

    def selection_clear(self, first, last=None):
        self.selection = ()

    def selection_set(self, index):
        self.selection = (index,)

    def see(self, index):
        pass


class Canvas(Widget):
    """Records draw calls; create_image validates a real PhotoImage."""

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.drawn = []
        self._next_id = 1

    def _add(self, kind, args, kw):
        self.drawn.append({"kind": kind, "args": args, **kw})
        self._next_id += 1
        return self._next_id

    def create_rectangle(self, *args, **kw):
        return self._add("rectangle", args, kw)

    def create_text(self, *args, **kw):
        return self._add("text", args, kw)

    def create_line(self, *args, **kw):
        return self._add("line", args, kw)

    def create_oval(self, *args, **kw):
        return self._add("oval", args, kw)

    def create_image(self, *args, **kw):
        image = kw.get("image")
        assert isinstance(image, PhotoImage), \
            "create_image must receive a built PhotoImage"
        return self._add("image", args, kw)

    def move(self, item, dx, dy):
        pass

    def delete(self, what="all"):
        if what == "all":
            self.drawn = []
        else:
            self.drawn = [d for d in self.drawn if d.get("tags") != what]


class Tk(Widget):
    def __init__(self):
        super().__init__(None)
        self._protocols = {}

    def title(self, text=None):
        pass

    def geometry(self, spec=None):
        pass

    def resizable(self, *a):
        pass

    def protocol(self, name, fn):
        self._protocols[name] = fn

    def attributes(self, *a, **kw):
        pass

    def after(self, ms, fn=None, *args):
        if fn is not None:
            AFTER_QUEUE.append(lambda: fn(*args))
        return f"after#{len(AFTER_QUEUE)}"

    def after_cancel(self, ident):
        pass

    def focus_get(self):
        return _FOCUSED[0]

    def clipboard_clear(self):
        CLIPBOARD[0] = ""

    def clipboard_append(self, text):
        CLIPBOARD[0] += str(text)

    def update(self):
        pass

    def mainloop(self):
        pass

    def destroy(self):
        self.destroyed = True
