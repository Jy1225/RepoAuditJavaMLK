import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase33_SwitchOneBranchLeak {
    public void run(String path, int mode) throws Exception {
        InputStream in = new FileInputStream(path);
        switch (mode) {
            case 0:
                in.close();
                break;
            case 1:
                System.out.println(in.read());
                break;
            default:
                in.close();
                break;
        }
    }
}
