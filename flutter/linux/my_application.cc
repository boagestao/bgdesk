#include "my_application.h"

#include <flutter_linux/flutter_linux.h>
#ifdef GDK_WINDOWING_X11
#include <gdk/gdkx.h>
#endif

#include "flutter/generated_plugin_registrant.h"

struct _MyApplication {
  GtkApplication parent_instance;
  char** dart_entrypoint_arguments;
};

G_DEFINE_TYPE(MyApplication, my_application, GTK_TYPE_APPLICATION)

GtkWidget *find_gl_area(GtkWidget *widget);
void try_set_transparent(GtkWindow* window, GdkScreen* screen, FlView* view);

extern bool gIsConnectionManager;
extern bool gIsInstallPage;

// Keep the incoming connection manager distinct from the main window for
// compositor rules, on both native Wayland (app_id) and X11/XWayland (WM_CLASS).
static constexpr char kConnectionManagerApplicationId[] =
    "bgdesk.connection-manager";

// One Flutter GtkWindow per process. A second GApplication activate must
// present this window instead of creating another FlView/engine.
static GtkWindow* g_app_window = NULL;

static void present_existing_window(GtkWindow* window) {
  if (window == NULL) {
    return;
  }
  gtk_widget_show(GTK_WIDGET(window));
  gtk_window_deiconify(window);
  gtk_window_present(window);
}

static void on_app_window_destroy(GtkWidget* widget, gpointer user_data) {
  (void)widget;
  (void)user_data;
  g_app_window = NULL;
}

// Implements GApplication::activate.
static void my_application_activate(GApplication* application) {
  if (g_app_window != NULL) {
    present_existing_window(g_app_window);
    return;
  }

  GList* windows = gtk_application_get_windows(GTK_APPLICATION(application));
  if (windows != NULL && windows->data != NULL) {
    g_app_window = GTK_WINDOW(windows->data);
    present_existing_window(g_app_window);
    return;
  }

  MyApplication* self = MY_APPLICATION(application);
  if (gIsConnectionManager) {
    // GtkWindow copies the program class at construction, before its first map.
    gdk_set_program_class(kConnectionManagerApplicationId);
  }
  GtkWindow* window =
      GTK_WINDOW(gtk_application_window_new(GTK_APPLICATION(application)));
  gtk_window_set_decorated(window, FALSE);
  // try setting icon for bgdesk, which uses the system cache 
  GtkIconTheme* theme = gtk_icon_theme_get_default();
  gint icons[4] = {256, 128, 64, 32};
  for (int i = 0; i < 4; i++) {
    GdkPixbuf* icon = gtk_icon_theme_load_icon(theme, "bgdesk", icons[i], GTK_ICON_LOOKUP_NO_SVG, NULL);
    if (icon != nullptr) {
      gtk_window_set_icon(window, icon);
    }
  }
  // Use a header bar when running in GNOME as this is the common style used
  // by applications and is the setup most users will be using (e.g. Ubuntu
  // desktop).
  // If running on X and not using GNOME then just use a traditional title bar
  // in case the window manager does more exotic layout, e.g. tiling.
  // If running on Wayland assume the header bar will work (may need changing
  // if future cases occur).
  gboolean use_header_bar = TRUE;
  GdkScreen* screen = NULL;
#ifdef GDK_WINDOWING_X11
  screen = gtk_window_get_screen(window);
  if (screen != NULL && GDK_IS_X11_SCREEN(screen)) {
    const gchar* wm_name = gdk_x11_screen_get_window_manager_name(screen);
    if (g_strcmp0(wm_name, "GNOME Shell") != 0) {
      use_header_bar = FALSE;
    }
  }
#endif
  if (use_header_bar) {
    GtkHeaderBar* header_bar = GTK_HEADER_BAR(gtk_header_bar_new());
    gtk_widget_show(GTK_WIDGET(header_bar));
    gtk_header_bar_set_title(header_bar, "BGDesk");
    gtk_header_bar_set_show_close_button(header_bar, TRUE);
    gtk_window_set_titlebar(window, GTK_WIDGET(header_bar));
  } else {
    gtk_window_set_title(window, "BGDesk");
  }

  // auto bdw = bitsdojo_window_from(window); // <--- add this line
  // bdw->setCustomFrame(true);               // <-- add this line
  int width = 800, height = 600;
  if (gIsConnectionManager) {
    width = 300;
    height = 490;
  }
  gtk_window_set_default_size(window, width, height);   // <-- comment this line
  // gtk_widget_show(GTK_WIDGET(window));
  gtk_widget_set_opacity(GTK_WIDGET(window), 0);

  g_autoptr(FlDartProject) project = fl_dart_project_new();
  fl_dart_project_set_dart_entrypoint_arguments(project, self->dart_entrypoint_arguments);

  FlView* view = fl_view_new(project);
  gtk_container_add(GTK_CONTAINER(window), GTK_WIDGET(view));

  try_set_transparent(window, gtk_window_get_screen(window), view);
  gtk_widget_show(GTK_WIDGET(window));
  gtk_widget_show(GTK_WIDGET(view));

  fl_register_plugins(FL_PLUGIN_REGISTRY(view));

  gtk_widget_grab_focus(GTK_WIDGET(view));

  g_app_window = window;
  g_signal_connect(window, "destroy", G_CALLBACK(on_app_window_destroy), NULL);
}

// Implements GApplication::local_command_line.
static gboolean my_application_local_command_line(GApplication* application, gchar*** arguments, int* exit_status) {
  MyApplication* self = MY_APPLICATION(application);
  // Strip out the first argument as it is the binary name.
  self->dart_entrypoint_arguments = g_strdupv(*arguments + 1);

  g_autoptr(GError) error = nullptr;
  if (!g_application_register(application, nullptr, &error)) {
     g_warning("Failed to register: %s", error->message);
     *exit_status = 1;
     return TRUE;
  }

  g_application_activate(application);
  *exit_status = 0;

  return TRUE;
}

// Implements GObject::dispose.
static void my_application_dispose(GObject* object) {
  MyApplication* self = MY_APPLICATION(object);
  g_clear_pointer(&self->dart_entrypoint_arguments, g_strfreev);
  G_OBJECT_CLASS(my_application_parent_class)->dispose(object);
}

static void my_application_class_init(MyApplicationClass* klass) {
  G_APPLICATION_CLASS(klass)->activate = my_application_activate;
  G_APPLICATION_CLASS(klass)->local_command_line = my_application_local_command_line;
  G_OBJECT_CLASS(klass)->dispose = my_application_dispose;
}

static void my_application_init(MyApplication* self) {}

MyApplication* my_application_new() {
  if (gIsConnectionManager) {
    // GTK 3's Wayland backend uses the program name for xdg_toplevel.app_id.
    // Set it before GApplication startup and before creating any windows.
    g_set_prgname(kConnectionManagerApplicationId);
  }
  const char* application_id = gIsConnectionManager
                                   ? kConnectionManagerApplicationId
                                   : APPLICATION_ID;
  // Default GApplication flags are unique: a second launch activates the
  // running instance instead of opening another GUI. `--install` keeps
  // G_APPLICATION_NON_UNIQUE so it can appear beside the main window, matching
  // the Windows whitelist in flutter/windows/runner/main.cpp.
  if (gIsInstallPage) {
    return MY_APPLICATION(g_object_new(my_application_get_type(),
                                       "application-id", application_id,
                                       "flags", G_APPLICATION_NON_UNIQUE,
                                       nullptr));
  }
  return MY_APPLICATION(g_object_new(my_application_get_type(),
                                     "application-id", application_id,
                                     nullptr));
}

GtkWidget *find_gl_area(GtkWidget *widget)
{
  if (GTK_IS_GL_AREA(widget)) {
    return widget;
  }

  if (GTK_IS_CONTAINER(widget)) {
    GList *children = gtk_container_get_children(GTK_CONTAINER(widget));
    for (GList *iter = children; iter != NULL; iter = g_list_next(iter)) {
      GtkWidget *child = GTK_WIDGET(iter->data);
      GtkWidget *gl_area = find_gl_area(child);
      if (gl_area != NULL) {
        g_list_free(children);
        return gl_area;
      }
    }
    g_list_free(children);
  }

  return NULL;
}

// https://github.com/flutter/flutter/issues/152154
// Remove this workaround when flutter version is updated.
void try_set_transparent(GtkWindow* window, GdkScreen* screen, FlView* view)
{
  GtkWidget *gl_area = NULL;

  printf("Try setting transparent\n");
  
  gl_area = find_gl_area(GTK_WIDGET(view));
  if (gl_area != NULL) {
    gtk_gl_area_set_has_alpha(GTK_GL_AREA(gl_area), TRUE);
  }

  if (screen != NULL) {
    GdkVisual *visual = NULL;
    gtk_widget_set_app_paintable(GTK_WIDGET(window), TRUE);
    visual = gdk_screen_get_rgba_visual(screen);
    if (visual != NULL && gdk_screen_is_composited(screen)) {
      gtk_widget_set_visual(GTK_WIDGET(window), visual);
    }
  }
}
