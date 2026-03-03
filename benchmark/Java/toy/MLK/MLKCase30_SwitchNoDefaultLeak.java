import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase30_SwitchNoDefaultLeak {
    public void run(String path, int mode) throws Exception {
        InputStream in = new FileInputStream(path);
        switch (mode) {
            case 0:
                in.close();
                break;
            case 1:
                in.close();
                break;
        }
    }
}
